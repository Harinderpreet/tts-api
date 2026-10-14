import type { TtsRequest } from '$lib/types/tts';

function escapeXml(value: string) {
  return value.replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F]/g, ' ')
    .replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;').replaceAll("'", '&apos;');
}

function numericValue(value: string, field: string) {
  const trimmed = value.trim();
  if (!/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?$/i.test(trimmed)) {
    throw new Error(`Invalid numeric ${field} value`);
  }
  const number = Number(trimmed);
  if (!Number.isFinite(number)) throw new Error(`${field} must be finite`);
  return number;
}

export function createSpeechSsml(request: TtsRequest) {
  // Keep the existing public multipliers and Python's truncation toward zero.
  const rate = Math.trunc((numericValue(request.speed, 'speed') - 1) * 100);
  const volume = Math.trunc(numericValue(request.volume, 'volume')) - 100;
  if (!Number.isFinite(rate) || !Number.isFinite(volume)) throw new Error('Speech rate or volume conversion overflowed');
  const pitch = `${/^[+-]/.test(request.pitch) ? '' : '+'}${request.pitch}Hz`;
  const language = request.voice.split('-').slice(0, 2).join('-');
  const style = escapeXml(request.style?.trim() || 'general');
  // Escape user text first; only recognized pause markers become actual XML elements.
  const content = escapeXml(request.text).replace(
    /\[break\s+(\d+(?:\.\d+)?)(ms|s)\]/gi,
    (_marker, duration: string, unit: string) => `<break time="${duration}${unit.toLowerCase()}"/>`
  );
  return `<speak xmlns="http://www.w3.org/2001/10/synthesis" xmlns:mstts="http://www.w3.org/2001/mstts" version="1.0" xml:lang="${escapeXml(language)}"><voice name="${escapeXml(request.voice)}"><mstts:express-as style="${style}" styledegree="2.0" role="default"><prosody rate="${rate >= 0 ? '+' : ''}${rate}%" pitch="${escapeXml(pitch)}" volume="${volume >= 0 ? '+' : ''}${volume}%">${content}</prosody></mstts:express-as></voice></speak>`;
}
