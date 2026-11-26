import {
  Appointment,
  CallProvision,
  CallSessionSummary,
  ClinicConfig,
  ClinicSnapshot,
  HealthStatus,
  TranscriptEntryDTO,
  UpdateClinicConfig,
} from '../types/clinic';

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly code?: string
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
  });

  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    let code: string | undefined;
    try {
      const errBody = (await res.json()) as { detail?: string; code?: string };
      if (errBody.detail) detail = errBody.detail;
      code = errBody.code;
    } catch {
      // Non-JSON response
    }
    throw new ApiError(detail, res.status, code);
  }

  return (await res.json()) as T;
}

export const clinicApi = {
  getHealth(signal?: AbortSignal): Promise<HealthStatus> {
    return requestJson<HealthStatus>('/api/v1/health', { signal });
  },

  getSnapshot(signal?: AbortSignal): Promise<ClinicSnapshot> {
    return requestJson<ClinicSnapshot>('/api/v1/clinic/snapshot', { signal });
  },

  updateConfig(payload: UpdateClinicConfig): Promise<ClinicConfig> {
    return requestJson<ClinicConfig>('/api/v1/config', {
      method: 'PATCH',
      body: JSON.stringify(payload),
    });
  },

  cancelAppointment(callerPhone: string, referenceCode: string): Promise<Appointment> {
    return requestJson<Appointment>('/api/v1/appointments/cancel', {
      method: 'POST',
      body: JSON.stringify({
        caller_phone: callerPhone,
        reference_code: referenceCode,
        phone_confirmed_by_caller: true,
      }),
    });
  },

  resetClinic(): Promise<ClinicSnapshot> {
    return requestJson<ClinicSnapshot>('/api/v1/clinic/reset', { method: 'POST' });
  },

  createCallSession(): Promise<CallProvision> {
    return requestJson<CallProvision>('/api/v1/calls', { method: 'POST' });
  },

  listCalls(signal?: AbortSignal): Promise<CallSessionSummary[]> {
    return requestJson<CallSessionSummary[]>('/api/v1/calls', { signal });
  },

  getCallTranscript(callId: string, signal?: AbortSignal): Promise<TranscriptEntryDTO[]> {
    return requestJson<TranscriptEntryDTO[]>(
      `/api/v1/calls/${encodeURIComponent(callId)}/transcript`,
      { signal }
    );
  },
};
