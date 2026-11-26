export interface ClinicConfig {
  clinic_name: string;
  agent_name: string;
  greeting_tone: 'warm' | 'formal';
  tts_speed: number;
  strict_phone_readback: boolean;
  updated_at: string;
}

export interface UpdateClinicConfig {
  clinic_name?: string;
  agent_name?: string;
  greeting_tone?: 'warm' | 'formal';
  tts_speed?: number;
  strict_phone_readback?: boolean;
}

export interface DoctorSlot {
  id: string;
  doctor_id: string;
  date: string;
  time: string;
  time_display: string;
  is_booked: boolean;
}

export interface Doctor {
  id: string;
  name: string;
  specialty: string;
  room: string;
  experience_years: number;
  initials: string;
  available_count: number;
  slots: DoctorSlot[];
}

export interface Appointment {
  id: string;
  reference_code: string;
  doctor_id: string;
  doctor_name: string;
  doctor_specialty: string;
  doctor_room: string;
  slot_id: string;
  date: string;
  time: string;
  time_display: string;
  caller_phone: string;
  caller_phone_display: string;
  patient_name: string;
  reason: string;
  status: 'confirmed' | 'cancelled';
  booked_via_call_id: string | null;
  created_at: string;
  cancelled_at: string | null;
}

export interface ClinicSnapshot {
  version: number;
  today: string;
  tomorrow: string;
  config: ClinicConfig;
  doctors: Doctor[];
  appointments: Appointment[];
  active_calls: number;
}

export interface HealthStatus {
  status: string;
  version: string;
  voice_ready: boolean;
  missing_keys: string[];
  llm_model: string;
  active_calls: number;
  state_version: number;
}

export interface CallProvision {
  call_id: string;
  ws_path: string;
  events_path: string;
}

export interface CallSessionSummary {
  call_id: string;
  state: 'created' | 'connecting' | 'connected' | 'ended' | 'error';
  created_at: string;
  connected_at: string | null;
  ended_at: string | null;
  caller_phone: string | null;
  phone_confirmed: boolean;
  turns_count: number;
  tool_calls_count: number;
  avg_llm_ttft_ms: number | null;
  outcome: string | null;
}

export interface TranscriptEntryDTO {
  id: number;
  call_id: string;
  role: 'caller' | 'agent' | 'tool' | 'booking' | 'cancellation';
  text: string;
  latency_ms: number | null;
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface EventEnvelope<T = Record<string, unknown>> {
  id: number;
  scope: 'clinic' | 'call';
  type: string;
  version: number;
  call_id: string | null;
  timestamp?: string;
  data: T;
}

export interface CallLatencyMetrics {
  llmTtftMs: number | null;
  avgLlmTtftMs: number | null;
  toolExecMs: number | null;
  lastTool: string | null;
}

export type StreamStatus = 'connecting' | 'live' | 'reconnecting';

export type CallStatus = 'idle' | 'ringing' | 'connected' | 'ended';

export type PipelineStage = 'idle' | 'vad' | 'stt' | 'llm' | 'tool' | 'tts';

export type NavTab = 'desk' | 'calls' | 'agent';

export interface TranscriptItem {
  id: string;
  role: 'caller' | 'agent' | 'tool' | 'booking' | 'cancellation';
  text: string;
  timestamp: string;
  latencyMs?: number | null;
  appointment?: Appointment;
}
