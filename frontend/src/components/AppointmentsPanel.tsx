import { useMemo, useState } from 'react';
import { X } from 'lucide-react';
import { Appointment } from '../types/clinic';

interface AppointmentsPanelProps {
  appointments: Appointment[];
  searchQuery: string;
  highlightedRows: Record<string, 'booked' | 'cancelled'>;
  onCancelAppointment?: (callerPhone: string, referenceCode: string) => Promise<void>;
}

export function AppointmentsPanel({
  appointments,
  searchQuery,
  highlightedRows,
  onCancelAppointment,
}: AppointmentsPanelProps) {
  const [cancellingId, setCancellingId] = useState<string | null>(null);

  const filtered = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    if (!q) return appointments;
    return appointments.filter(
      (a) =>
        a.caller_phone.includes(q.replace(/\D/g, '') || q) ||
        a.caller_phone_display.toLowerCase().includes(q) ||
        a.doctor_name.toLowerCase().includes(q) ||
        a.patient_name.toLowerCase().includes(q) ||
        a.reference_code.toLowerCase().includes(q)
    );
  }, [appointments, searchQuery]);

  const handleDeskCancel = async (appt: Appointment) => {
    if (!onCancelAppointment) return;
    setCancellingId(appt.id);
    try {
      await onCancelAppointment(appt.caller_phone, appt.reference_code);
    } finally {
      setCancellingId(null);
    }
  };

  return (
    <section aria-labelledby="appointments-heading">
      <div className="section-bar">
        <h2 id="appointments-heading" className="section-label">
          Appointments
        </h2>
        <span className="section-count mono">{filtered.length}</span>
      </div>

      {filtered.length === 0 ? (
        <div className="quiet-empty">No appointments.</div>
      ) : (
        <div
          tabIndex={0}
          role="region"
          aria-labelledby="appointments-table-caption"
          className="table-wrapper"
        >
          <table className="appointments-table">
            <caption id="appointments-table-caption" className="sr-only">
              Appointments ledger
            </caption>
            <thead>
              <tr>
                <th scope="col">Phone</th>
                <th scope="col">Doctor</th>
                <th scope="col">Slot</th>
                <th scope="col">Status</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((appt) => {
                const highlight = highlightedRows[appt.id];
                const rowClass =
                  highlight === 'booked'
                    ? 'row-highlight-booked'
                    : highlight === 'cancelled'
                      ? 'row-highlight-cancelled'
                      : '';

                return (
                  <tr key={appt.id} className={rowClass}>
                    <th scope="row">
                      <div className="appt-primary mono">{appt.caller_phone_display}</div>
                      <div className="appt-secondary mono">{appt.reference_code}</div>
                    </th>
                    <td>
                      <div className="appt-primary">{appt.doctor_name}</div>
                      <div className="appt-secondary">{appt.doctor_specialty}</div>
                    </td>
                    <td>
                      <div className="appt-primary mono">{appt.time_display}</div>
                      <div className="appt-secondary mono">{appt.date}</div>
                    </td>
                    <td>
                      <div className="status-cell">
                        <span className={`state-dot-pill ${appt.status}`}>
                          <span className="state-dot" aria-hidden="true" />
                          <span>{appt.status === 'confirmed' ? 'Confirmed' : 'Cancelled'}</span>
                        </span>
                        {appt.status === 'confirmed' && onCancelAppointment && (
                          <button
                            type="button"
                            className="desk-cancel-x"
                            onClick={() => void handleDeskCancel(appt)}
                            disabled={cancellingId === appt.id}
                            aria-label={`Cancel ${appt.reference_code}`}
                            title="Cancel"
                          >
                            <X size={12} />
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
