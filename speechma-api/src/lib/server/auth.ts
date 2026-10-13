import { timingSafeEqual } from 'node:crypto';

export function hasValidApiKey(headers: Headers, expected: string) {
  const supplied = headers.get('api-key');
  if (supplied === null) return false;
  const actualBytes = Buffer.from(supplied);
  const expectedBytes = Buffer.from(expected);
  return actualBytes.length === expectedBytes.length && timingSafeEqual(actualBytes, expectedBytes);
}
