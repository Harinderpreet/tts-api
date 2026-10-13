// Match the reference's local ISO timestamps without asserting a UTC offset.
export function localTimestamp(milliseconds = Date.now()) {
  const date = new Date(milliseconds);
  const local = new Date(milliseconds - date.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, -1);
}
