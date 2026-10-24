export interface ServerMetrics {
  timestamp: number;
  ready: boolean;
  maxConcurrent: number;
  host: { cpuPercent: number | null; memoryBytes: number; availableBytes: number; totalBytes: number };
}

export interface LoadLimits {
  maxConcurrent: number;
  maxJobs: number;
  durationSeconds: number;
  jobTimeoutSeconds: number;
}

export interface LoadJob {
  attempt: number;
  id: string | null;
  status: 'submitting' | 'queued' | 'processing' | 'completed' | 'failed' | 'unknown' | 'rejected';
  started: number;
  finished?: number;
  message?: string;
}

export interface LoadSnapshot {
  started: number | null;
  target: number;
  pending: number;
  outstanding: number;
  attempted: number;
  completed: number;
  failed: number;
  unknown: number;
  rejected: number;
  peakOutstanding: number;
  p50Seconds: number | null;
  p95Seconds: number | null;
  draining: boolean;
  ended: boolean;
  locked: boolean;
  message: string;
  jobs: LoadJob[];
}
