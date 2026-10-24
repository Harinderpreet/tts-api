import { cpus, freemem, totalmem } from 'node:os';
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import type { ServerMetrics } from '$lib/types/load-test';

type Resources = Pick<ServerMetrics, 'process' | 'host' | 'group'>;
let previous: { time: number; processCpu: number; hostCpu: number; hostIdle: number; groupCpu: number | null } | undefined;
let cached: Resources | undefined;
let pending: Promise<Resources> | undefined;
let sampledAt = 0;

// The sampler is shared by all tabs in this Node process; there is no background worker.
export function readSystemMetrics(): Promise<Resources> {
  if (cached && Date.now() - sampledAt < 1000) return Promise.resolve(cached);
  return pending ??= sample().then((value) => {
    cached = value;
    sampledAt = Date.now();
    return value;
  }).finally(() => { pending = undefined; });
}

async function sample(): Promise<Resources> {
  const time = performance.now();
  const processCpu = process.cpuUsage();
  const processTotal = processCpu.user + processCpu.system;
  const host = cpus().reduce((sum, cpu) => ({
    total: sum.total + Object.values(cpu.times).reduce((a, b) => a + b, 0),
    idle: sum.idle + cpu.times.idle
  }), { total: 0, idle: 0 });
  const [memoryInfo, group] = await Promise.all([
    readFile('/proc/meminfo', 'utf8').catch(() => ''), readResourceGroup()
  ]);
  const availableMatch = /^MemAvailable:\s+(\d+) kB$/m.exec(memoryInfo);
  const available = availableMatch ? Number(availableMatch[1]) * 1024 : freemem();
  const totalMatch = /^MemTotal:\s+(\d+) kB$/m.exec(memoryInfo);
  const total = totalMatch ? Number(totalMatch[1]) * 1024 : totalmem();
  const elapsed = previous ? (time - previous.time) * 1000 : 0;
  const hostElapsed = previous ? host.total - previous.hostCpu : 0;
  const percent = (value: number) => Math.round(Math.max(0, value) * 10) / 10;
  const result: Resources = {
    process: {
      cpuPercent: previous && elapsed > 0 ? percent((processTotal - previous.processCpu) / elapsed * 100) : null,
      memoryBytes: process.memoryUsage.rss()
    },
    host: {
      cpuPercent: previous && hostElapsed > 0 ? percent((1 - (host.idle - previous.hostIdle) / hostElapsed) * 100) : null,
      memoryBytes: total - available, availableBytes: available, totalBytes: total
    },
    group: group ? {
      cpuPercent: previous?.groupCpu != null && elapsed > 0 ? percent((group.cpuUsec - previous.groupCpu) / elapsed * 100) : null,
      cpuLimitCores: group.cpuLimitCores,
      memoryBytes: group.memoryBytes, memoryLimitBytes: group.memoryLimitBytes
    } : null
  };
  previous = { time, processCpu: processTotal, hostCpu: host.total, hostIdle: host.idle, groupCpu: group?.cpuUsec ?? null };
  return result;
}

// Read the process's own cgroup v2, rather than exposing Docker daemon access to the app.
async function readResourceGroup() {
  try {
    const membership = await readFile('/proc/self/cgroup', 'utf8');
    const path = /^0::(.*)$/m.exec(membership)?.[1];
    if (path === undefined) return null;
    const directory = join('/sys/fs/cgroup', path);
    const [cpu, quota, memory, limit] = await Promise.all([
      readFile(join(directory, 'cpu.stat'), 'utf8'), readFile(join(directory, 'cpu.max'), 'utf8'),
      readFile(join(directory, 'memory.current'), 'utf8'), readFile(join(directory, 'memory.max'), 'utf8')
    ]);
    const usage = /^usage_usec (\d+)$/m.exec(cpu)?.[1];
    if (!usage) return null;
    const [budget, period] = quota.trim().split(/\s+/);
    return {
      cpuUsec: Number(usage), cpuLimitCores: budget === 'max' ? null : Number(budget) / Number(period),
      memoryBytes: Number(memory.trim()), memoryLimitBytes: limit.trim() === 'max' ? null : Number(limit.trim())
    };
  } catch { return null; }
}
