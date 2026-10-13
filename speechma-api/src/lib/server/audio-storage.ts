import { mkdir, open, readdir, rename, stat, unlink } from 'node:fs/promises';
import { join } from 'node:path';
import { Readable } from 'node:stream';
import type { ListedJob } from '$lib/types/tts';
import { localTimestamp } from './timestamps';

// IDs remain plain strings at the HTTP boundary; unsafe filesystem names never resolve.
function safeId(id: string) {
  return /^[a-zA-Z0-9_-]+$/.test(id);
}

export class AudioStorage {
  constructor(private readonly directory: string) {}

  async initialize() {
    await mkdir(this.directory, { recursive: true });
  }

  private path(id: string, temporary = false) {
    if (!safeId(id)) throw new Error('Invalid audio file identifier');
    return join(this.directory, `${id}.mp3${temporary ? '.temp' : ''}`);
  }

  async info(id: string) {
    if (!safeId(id)) return null;
    try {
      const info = await stat(this.path(id));
      return info.isFile() ? info : null;
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === 'ENOENT') return null;
      throw error;
    }
  }

  async save(id: string, chunks: AsyncIterable<Uint8Array>, signal: AbortSignal) {
    const temporaryPath = this.path(id, true);
    signal.throwIfAborted();
    const file = await open(temporaryPath, 'wx');
    let size = 0;
    try {
      for await (const chunk of chunks) {
        signal.throwIfAborted();
        await file.writeFile(chunk);
        size += chunk.byteLength;
      }
      signal.throwIfAborted();
      if (!size) throw new Error('Speech provider returned no audio');
      await file.close();
      signal.throwIfAborted();
      await rename(temporaryPath, this.path(id));
      if (signal.aborted) {
        await this.remove(id);
        signal.throwIfAborted();
      }
    } finally {
      await file.close();
      await unlink(temporaryPath).catch((error: NodeJS.ErrnoException) => {
        if (error.code !== 'ENOENT') throw error;
      });
    }
  }

  async download(id: string) {
    if (!safeId(id)) return null;
    let file;
    try {
      file = await open(this.path(id), 'r');
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === 'ENOENT') return null;
      throw error;
    }
    try {
      const info = await file.stat();
      if (!info.isFile() || info.size < 100) {
        await file.close();
        return { size: info.size, stream: null };
      }
      const stream = Readable.toWeb(file.createReadStream({ highWaterMark: 1024 * 1024 }));
      return { size: info.size, stream: stream as ReadableStream<Uint8Array> };
    } catch (error) {
      await file.close();
      throw error;
    }
  }

  async remove(id: string) {
    if (!safeId(id)) return false;
    try {
      await unlink(this.path(id));
      return true;
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === 'ENOENT') return false;
      throw error;
    }
  }

  async list(): Promise<ListedJob[]> {
    const jobs: ListedJob[] = [];
    for (const name of await readdir(this.directory)) {
      if (!name.endsWith('.mp3')) continue;
      const job_id = name.slice(0, -4);
      const info = await this.info(job_id);
      if (info) jobs.push({
        job_id, status: 'completed', audio_exists: true,
        created_at: localTimestamp(info.mtimeMs), file_size: info.size
      });
    }
    return jobs;
  }

  async removeExpired(ageMs: number, activeIds: Set<string>) {
    const removed: string[] = [];
    const now = Date.now();
    for (const name of await readdir(this.directory)) {
      if (!name.endsWith('.mp3') && !name.endsWith('.mp3.temp')) continue;
      const id = name.replace(/\.mp3(?:\.temp)?$/, '');
      if (!safeId(id) || activeIds.has(id)) continue;
      const path = join(this.directory, name);
      try {
        const info = await stat(path);
        if (info.isFile() && now - info.mtimeMs > ageMs) {
          await unlink(path);
          removed.push(id);
        }
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error;
      }
    }
    return removed;
  }
}
