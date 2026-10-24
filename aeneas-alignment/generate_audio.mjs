// Reuse Speechma's existing synthesis implementation without starting a service.
import { readFile, writeFile, rename, unlink } from 'node:fs/promises';
import path from 'node:path';
import { createSpeechSsml } from '../speechma-api/src/lib/tts/ssml.ts';
import { synthesizeSsml } from '../speechma-api/src/lib/server/tts/translator.ts';

const [transcriptPath, voice, directory] = process.argv.slice(2);
if (!transcriptPath || !voice || !directory) {
  throw new Error('Provide transcript path, documented Microsoft voice ID and output directory');
}
const text = await readFile(transcriptPath, 'utf8');
const temporary = path.join(directory, 'speech.mp3.partial');
const started = performance.now();
try {
  const chunks = [];
  const ssml = createSpeechSsml({ text, voice, pitch: '0', speed: '1', volume: '100', style: 'general' });
  for await (const chunk of synthesizeSsml(ssml, AbortSignal.timeout(180000))) {
    chunks.push(Buffer.from(chunk));
  }
  const audio = Buffer.concat(chunks);
  await writeFile(temporary, audio, { flag: 'wx' });
  await rename(temporary, path.join(directory, 'speech.mp3'));
  const report = {
    provider: 'Existing Speechma Microsoft Translator speech adapter',
    voice, characters: [...text].length, bytes: audio.length,
    generation_seconds: Math.round((performance.now() - started) / 10) / 100,
  };
  await writeFile(path.join(directory, 'generation.json'), JSON.stringify(report, null, 2) + '\n', { flag: 'wx' });
  console.log(JSON.stringify(report));
} catch (error) {
  await unlink(temporary).catch(() => {});
  const messages = [];
  for (let cause = error; cause && messages.length < 5; cause = cause.cause) {
    messages.push(cause.message ?? String(cause));
  }
  console.error(messages.join(': '));
  process.exitCode = 1;
}
