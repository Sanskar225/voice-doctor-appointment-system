import { useCallback, useEffect, useReducer, useRef, useState } from 'react';
import { clinicApi } from '../api/clinicApi';
import {
  clinicReducer,
  DEFAULT_CLINIC_CONFIG,
  initialClinicState,
} from '../state/clinicReducer';
import {
  Appointment,
  ClinicConfig,
  ClinicSnapshot,
  DoctorSlot,
  EventEnvelope,
  UpdateClinicConfig,
} from '../types/clinic';

const HIGHLIGHT_MS = 4200;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function isAppointmentDelta(
  data: Record<string, unknown>
): data is { appointment: Appointment; slot: DoctorSlot } {
  return (
    isRecord(data.appointment) &&
    typeof data.appointment.id === 'string' &&
    isRecord(data.slot) &&
    typeof data.slot.id === 'string'
  );
}

function isConfigPayload(data: Record<string, unknown>): data is { config: ClinicConfig } {
  return isRecord(data.config) && typeof data.config.clinic_name === 'string';
}

function isClinicSnapshotPayload(
  data: Record<string, unknown>
): data is ClinicSnapshot & Record<string, unknown> {
  return (
    Array.isArray(data.doctors) &&
    Array.isArray(data.appointments) &&
    typeof data.today === 'string' &&
    typeof data.tomorrow === 'string'
  );
}

export function useClinicSync() {
  const [state, dispatch] = useReducer(clinicReducer, initialClinicState);
  const [resetting, setResetting] = useState(false);

  const versionRef = useRef(0);
  versionRef.current = state.version;

  const timersRef = useRef<Map<string, number>>(new Map());

  const scheduleTimer = useCallback((key: string, fn: () => void, ms: number) => {
    const existing = timersRef.current.get(key);
    if (existing !== undefined) {
      window.clearTimeout(existing);
    }
    const id = window.setTimeout(() => {
      timersRef.current.delete(key);
      fn();
    }, ms);
    timersRef.current.set(key, id);
  }, []);

  const syncSnapshot = useCallback(async (signal?: AbortSignal) => {
    try {
      const [snapshot, health] = await Promise.all([
        clinicApi.getSnapshot(signal),
        clinicApi.getHealth(signal),
      ]);
      dispatch({ type: 'SNAPSHOT_LOADED', snapshot });
      dispatch({ type: 'HEALTH_LOADED', health });
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') return;
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void syncSnapshot(controller.signal);

    const stream = new EventSource('/api/v1/events');

    stream.onopen = () => {
      dispatch({ type: 'STREAM_STATUS', status: 'live' });
    };

    stream.onerror = () => {
      dispatch({ type: 'STREAM_STATUS', status: 'reconnecting' });
    };

    stream.onmessage = (ev: MessageEvent<string>) => {
      try {
        const envelope = JSON.parse(ev.data) as EventEnvelope;
        const { type, version, data } = envelope;

        if (type === 'stream.connected') {
          dispatch({ type: 'STREAM_STATUS', status: 'live' });
          if (versionRef.current === 0 || version > versionRef.current) {
            void syncSnapshot();
          }
          return;
        }

        if (type === 'calls.count_changed') {
          dispatch({
            type: 'CALLS_COUNT_CHANGED',
            activeCalls: Number(data.active_calls ?? 0),
          });
          return;
        }

        if (type === 'config.updated' && isConfigPayload(data)) {
          dispatch({ type: 'CONFIG_UPDATED', version, config: data.config });
          return;
        }

        if (type === 'clinic.reset' && isClinicSnapshotPayload(data)) {
          dispatch({
            type: 'SNAPSHOT_LOADED',
            snapshot: {
              version,
              today: data.today,
              tomorrow: data.tomorrow,
              config: isRecord(data.config)
                ? (data.config as unknown as ClinicConfig)
                : DEFAULT_CLINIC_CONFIG,
              doctors: data.doctors,
              appointments: data.appointments,
              active_calls: Number(data.active_calls ?? 0),
            },
          });
          return;
        }

        if (versionRef.current > 0 && version > versionRef.current + 1) {
          void syncSnapshot();
          return;
        }

        if (type === 'appointment.booked' && isAppointmentDelta(data)) {
          const { appointment, slot } = data;
          dispatch({ type: 'APPOINTMENT_BOOKED', version, appointment, slot });
          scheduleTimer(
            `row:${appointment.id}`,
            () => dispatch({ type: 'CLEAR_ROW_HIGHLIGHT', appointmentId: appointment.id }),
            HIGHLIGHT_MS
          );
          scheduleTimer(
            `slot:${slot.id}`,
            () => dispatch({ type: 'CLEAR_SLOT_HIGHLIGHT', slotId: slot.id }),
            HIGHLIGHT_MS
          );
        } else if (type === 'appointment.cancelled' && isAppointmentDelta(data)) {
          const { appointment, slot } = data;
          dispatch({ type: 'APPOINTMENT_CANCELLED', version, appointment, slot });
          scheduleTimer(
            `row:${appointment.id}`,
            () => dispatch({ type: 'CLEAR_ROW_HIGHLIGHT', appointmentId: appointment.id }),
            HIGHLIGHT_MS
          );
          scheduleTimer(
            `slot:${slot.id}`,
            () => dispatch({ type: 'CLEAR_SLOT_HIGHLIGHT', slotId: slot.id }),
            HIGHLIGHT_MS
          );
        }
      } catch {
        // Ignore keep-alive frames
      }
    };

    const activeTimers = timersRef.current;
    return () => {
      controller.abort();
      stream.close();
      for (const id of activeTimers.values()) {
        window.clearTimeout(id);
      }
      activeTimers.clear();
    };
  }, [scheduleTimer, syncSnapshot]);

  const resetDemo = useCallback(async () => {
    setResetting(true);
    try {
      const snapshot = await clinicApi.resetClinic();
      dispatch({ type: 'SNAPSHOT_LOADED', snapshot });
    } finally {
      setResetting(false);
    }
  }, []);

  const saveConfig = useCallback(async (patch: UpdateClinicConfig) => {
    const updated = await clinicApi.updateConfig(patch);
    dispatch({ type: 'CONFIG_UPDATED', version: versionRef.current, config: updated });
    return updated;
  }, []);

  const cancelFromDesk = useCallback(async (callerPhone: string, referenceCode: string) => {
    await clinicApi.cancelAppointment(callerPhone, referenceCode);
  }, []);

  return {
    state,
    resetting,
    resetDemo,
    saveConfig,
    cancelFromDesk,
    refresh: syncSnapshot,
  };
}
