import { readFile } from 'node:fs/promises';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';

const execute = promisify(execFile);
const mib = (bytes) => Math.round(bytes / 1024 / 1024);

// Run on the Linux host to measure host resources. A laptop measures the laptop.
export class ResourceMonitor {
  previousCpu;

  async sample(containers) {
    const [host, docker] = await Promise.all([
      this.host(),
      Promise.all(containers.map((container) => this.container(container)))
    ]);
    return { host, containers: docker };
  }

  async host() {
    try {
      const [stat, memory] = await Promise.all([
        readFile('/proc/stat', 'utf8'), readFile('/proc/meminfo', 'utf8')
      ]);
      // Guest times are already included in user/nice; exclude them from the sum.
      const ticks = stat.split('\n')[0].trim().split(/\s+/).slice(1, 9).map(Number);
      const total = ticks.reduce((sum, value) => sum + value, 0);
      const idle = ticks[3] + ticks[4];
      const previous = this.previousCpu;
      this.previousCpu = { total, idle };
      const elapsed = previous ? total - previous.total : 0;
      const fields = Object.fromEntries([...memory.matchAll(/^(\w+):\s+(\d+) kB$/gm)]
        .map((match) => [match[1], Number(match[2]) * 1024]));
      return {
        cpu_percent: elapsed > 0 ? Math.round(1000 * (1 - (idle - previous.idle) / elapsed)) / 10 : null,
        memory_used_mib: mib(fields.MemTotal - fields.MemAvailable),
        memory_total_mib: mib(fields.MemTotal),
        memory_available_mib: mib(fields.MemAvailable)
      };
    } catch {
      return { unavailable: 'Host metrics require Linux /proc on the measured server.' };
    }
  }

  async container(name) {
    try {
      const { stdout } = await execute('docker', [
        'stats', '--no-stream', '--format', '{{json .}}', '--', name
      ], { timeout: 8000, maxBuffer: 1024 * 1024 });
      const stats = JSON.parse(stdout.trim());
      return {
        name, cpu_percent: Number(stats.CPUPerc.replace('%', '')),
        memory: stats.MemUsage, memory_percent: Number(stats.MemPerc.replace('%', ''))
      };
    } catch {
      return { name, unavailable: 'Cannot read Docker stats; check container name and Docker access.' };
    }
  }
}
