// Check the existing authenticated endpoint without printing the key or response body.
try {
  if (!process.env.API_KEY) process.exit(1);
  const response = await fetch(`http://127.0.0.1:${process.env.PORT || '3000'}/health`, {
    headers: { 'api-key': process.env.API_KEY },
    signal: AbortSignal.timeout(5000)
  });
  if (!response.ok) process.exit(1);
  const health = await response.json();
  process.exit(health.status === 'healthy' ? 0 : 1);
} catch {
  process.exit(1);
}
