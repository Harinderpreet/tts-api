import { cpus, freemem, totalmem } from 'node:os';
import { readFile } from 'node:fs/promises';
import type { ServerMetrics } from '$lib/types/load-test';

type Resources = Pick<ServerMetrics, 'host'>;
let previous: { hostCpu: number; hostIdle: number } | undefined;
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
  const host = cpus().reduce((sum, cpu) => ({
    total: sum.total + Object.values(cpu.times).reduce((a, b) => a + b, 0),
    idle: sum.idle + cpu.times.idle
  }), { total: 0, idle: 0 });
  const memoryInfo = await readFile('/proc/meminfo', 'utf8').catch(() => '');
  const availableMatch = /^MemAvailable:\s+(\d+) kB$/m.exec(memoryInfo);
  const available = availableMatch ? Number(availableMatch[1]) * 1024 : freemem();
  const totalMatch = /^MemTotal:\s+(\d+) kB$/m.exec(memoryInfo);
  const total = totalMatch ? Number(totalMatch[1]) * 1024 : totalmem();
  const hostElapsed = previous ? host.total - previous.hostCpu : 0;
  const percent = (value: number) => Math.round(Math.max(0, value) * 10) / 10;
  const result: Resources = {
    host: {
      cpuPercent: previous && hostElapsed > 0 ? percent((1 - (host.idle - previous.hostIdle) / hostElapsed) * 100) : null,
      memoryBytes: total - available, availableBytes: available, totalBytes: total
    }
  };
  previous = { hostCpu: host.total, hostIdle: host.idle };
  return result;
}
