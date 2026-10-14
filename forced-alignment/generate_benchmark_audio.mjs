// Generate a saved narration through the existing Speechma API; never log credentials.
import { readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';

const [endpoint, directory] = process.argv.slice(2);
if (!endpoint || !directory || !process.env.API_KEY) {
  throw new Error('Provide endpoint, output directory and API_KEY in the environment');
}
const transcript = (await readFile(path.join(directory, 'transcript.txt'), 'utf8')).trim();
const paragraphs = transcript.split(/\n\s*\n/);
const parts = [];
const started = performance.now();
for (let offset = 0; offset < paragraphs.length; offset += 4) {
  const text = paragraphs.slice(offset, offset + 4).join('\n\n');
  const response = await fetch(`${endpoint}/tts`, {
    method: 'POST', headers: { 'api-key': process.env.API_KEY, 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, voice: 'en-US-AriaNeural', pitch: '0', speed: '1', volume: '100', style: 'general' }),
    signal: AbortSignal.timeout(30000),
  });
  if (!response.ok) throw new Error(`Speech submission returned HTTP ${response.status}`);
  const { job_id } = await response.json();
  if (typeof job_id !== 'string') throw new Error('Speech response did not contain job_id');
  const deadline = Date.now() + 600000;
  let complete = false;
  while (Date.now() < deadline) {
    const statusResponse = await fetch(`${endpoint}/tts/status/${encodeURIComponent(job_id)}`, {
      headers: { 'api-key': process.env.API_KEY }, signal: AbortSignal.timeout(30000),
    });
    if (!statusResponse.ok) throw new Error(`Status returned HTTP ${statusResponse.status}`);
    const { status } = await statusResponse.json();
    if (status === 'failed') throw new Error('Speech generation failed');
    if (status === 'completed') { complete = true; break; }
    await delay(1000);
  }
  if (!complete) throw new Error('Speech generation timed out');
  const audio = await fetch(`${endpoint}/tts/audio/${encodeURIComponent(job_id)}`, {
    headers: { 'api-key': process.env.API_KEY }, signal: AbortSignal.timeout(60000),
  });
  if (!audio.ok) throw new Error(`Audio returned HTTP ${audio.status}`);
  const bytes = Buffer.from(await audio.arrayBuffer());
  const filename = `part-${parts.length + 1}.mp3`;
  await writeFile(path.join(directory, filename), bytes, { flag: 'wx' });
  parts.push({ file: filename, job_id, characters: text.length, words: text.split(/\s+/).length, bytes: bytes.length });
  console.log(`Saved narration part ${parts.length}: ${bytes.length} bytes`);
}
await writeFile(path.join(directory, 'generation.json'), JSON.stringify({
  voice: 'en-US-AriaNeural', language: 'eng', characters: transcript.length,
  words: transcript.split(/\s+/).length, generation_seconds: (performance.now() - started) / 1000, parts,
}, null, 2), { flag: 'wx' });
