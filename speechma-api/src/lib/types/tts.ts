export interface TtsRequest {
  text: string;
  voice: string;
  pitch: string;
  speed: string;
  volume: string;
  style?: string;
}

export type JobStatus = 'queued' | 'processing' | 'completed' | 'failed';

export interface Job {
  job_id: string;
  request: TtsRequest;
  status: JobStatus;
  created_at: number;
  start_time?: number;
  end_time?: number;
  error_message?: string;
}

export type ListedJob = {
  job_id: string;
  created_at: string;
} & (
  | { status: 'completed'; audio_exists: true; file_size: number }
  | { status: JobStatus; audio_exists: false; text: string }
);

export interface WebhookPayload {
  job_id: string;
  status: 'completed' | 'failed' | 'deleted';
  timestamp: string | null;
  message?: string;
  processing_time_seconds?: number;
}
