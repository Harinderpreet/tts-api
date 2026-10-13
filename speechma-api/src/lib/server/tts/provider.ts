import type { TtsRequest } from '$lib/types/tts';
import { createSpeechSsml } from './ssml';
import { synthesizeSsml } from './translator';

/** Internal boundary between the queue and the Microsoft Translator speech method. */
export interface SpeechProvider {
  /** Yield MP3 bytes; honor cancellation and release transport resources on abort. */
  synthesize(request: TtsRequest, signal: AbortSignal): Promise<AsyncIterable<Uint8Array>>;
}

export const speechProvider: SpeechProvider = {
  async synthesize(request, signal) {
    signal.throwIfAborted();
    return synthesizeSsml(createSpeechSsml(request), signal);
  }
};
