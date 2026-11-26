import {
  Appointment,
  ClinicConfig,
  ClinicSnapshot,
  Doctor,
  DoctorSlot,
  HealthStatus,
  StreamStatus,
} from '../types/clinic';

export interface ClinicState {
  version: number;
  today: string;
  tomorrow: string;
  config: ClinicConfig;
  doctors: Doctor[];
  appointments: Appointment[];
  activeCalls: number;
  health: HealthStatus | null;
  streamStatus: StreamStatus;
  highlightedRows: Record<string, 'booked' | 'cancelled'>;
  highlightedSlots: Record<string, 'booked' | 'freed'>;
}

export type ClinicAction =
  | { type: 'HEALTH_LOADED'; health: HealthStatus }
  | { type: 'SNAPSHOT_LOADED'; snapshot: ClinicSnapshot }
  | { type: 'CONFIG_UPDATED'; version: number; config: ClinicConfig }
  | { type: 'STREAM_STATUS'; status: StreamStatus }
  | { type: 'CALLS_COUNT_CHANGED'; activeCalls: number }
  | {
      type: 'APPOINTMENT_BOOKED';
      version: number;
      appointment: Appointment;
      slot: DoctorSlot;
    }
  | {
      type: 'APPOINTMENT_CANCELLED';
      version: number;
      appointment: Appointment;
      slot: DoctorSlot;
    }
  | { type: 'CLEAR_ROW_HIGHLIGHT'; appointmentId: string }
  | { type: 'CLEAR_SLOT_HIGHLIGHT'; slotId: string };

export const DEFAULT_CLINIC_CONFIG: ClinicConfig = {
  clinic_name: 'Aurelia Health',
  agent_name: 'Maya',
  greeting_tone: 'warm',
  tts_speed: 1.02,
  strict_phone_readback: true,
  updated_at: '',
};

export const initialClinicState: ClinicState = {
  version: 0,
  today: '',
  tomorrow: '',
  config: DEFAULT_CLINIC_CONFIG,
  doctors: [],
  appointments: [],
  activeCalls: 0,
  health: null,
  streamStatus: 'connecting',
  highlightedRows: {},
  highlightedSlots: {},
};

function updateDoctorSlot(doctors: Doctor[], updatedSlot: DoctorSlot): Doctor[] {
  return doctors.map((doc) => {
    if (doc.id !== updatedSlot.doctor_id) return doc;
    const nextSlots = doc.slots.map((s) =>
      s.id === updatedSlot.id ? { ...s, is_booked: updatedSlot.is_booked } : s
    );
    return {
      ...doc,
      slots: nextSlots,
      available_count: nextSlots.filter((s) => !s.is_booked).length,
    };
  });
}

function upsertAppointment(
  appointments: Appointment[],
  incoming: Appointment
): Appointment[] {
  const idx = appointments.findIndex((a) => a.id === incoming.id);
  if (idx === -1) {
    return [incoming, ...appointments];
  }
  const copy = [...appointments];
  copy[idx] = incoming;
  return copy;
}

export function clinicReducer(state: ClinicState, action: ClinicAction): ClinicState {
  switch (action.type) {
    case 'HEALTH_LOADED':
      return {
        ...state,
        health: action.health,
        activeCalls: action.health.active_calls,
      };

    case 'SNAPSHOT_LOADED':
      return {
        ...state,
        version: action.snapshot.version,
        today: action.snapshot.today,
        tomorrow: action.snapshot.tomorrow,
        config: action.snapshot.config ?? state.config,
        doctors: action.snapshot.doctors,
        appointments: action.snapshot.appointments,
        activeCalls: action.snapshot.active_calls,
      };

    case 'CONFIG_UPDATED':
      return {
        ...state,
        version: Math.max(state.version, action.version),
        config: action.config,
      };

    case 'STREAM_STATUS':
      return {
        ...state,
        streamStatus: action.status,
      };

    case 'CALLS_COUNT_CHANGED':
      return {
        ...state,
        activeCalls: action.activeCalls,
      };

    case 'APPOINTMENT_BOOKED':
      if (action.version <= state.version) return state;
      return {
        ...state,
        version: action.version,
        doctors: updateDoctorSlot(state.doctors, action.slot),
        appointments: upsertAppointment(state.appointments, action.appointment),
        highlightedRows: {
          ...state.highlightedRows,
          [action.appointment.id]: 'booked',
        },
        highlightedSlots: {
          ...state.highlightedSlots,
          [action.slot.id]: 'booked',
        },
      };

    case 'APPOINTMENT_CANCELLED':
      if (action.version <= state.version) return state;
      return {
        ...state,
        version: action.version,
        doctors: updateDoctorSlot(state.doctors, action.slot),
        appointments: upsertAppointment(state.appointments, action.appointment),
        highlightedRows: {
          ...state.highlightedRows,
          [action.appointment.id]: 'cancelled',
        },
        highlightedSlots: {
          ...state.highlightedSlots,
          [action.slot.id]: 'freed',
        },
      };

    case 'CLEAR_ROW_HIGHLIGHT': {
      if (!(action.appointmentId in state.highlightedRows)) return state;
      const next = { ...state.highlightedRows };
      delete next[action.appointmentId];
      return { ...state, highlightedRows: next };
    }

    case 'CLEAR_SLOT_HIGHLIGHT': {
      if (!(action.slotId in state.highlightedSlots)) return state;
      const next = { ...state.highlightedSlots };
      delete next[action.slotId];
      return { ...state, highlightedSlots: next };
    }

    default:
      return state;
  }
}
