import { useMemo, useState } from 'react';
import { Doctor } from '../types/clinic';
import { formatDayLabel } from '../utils/date';

interface DoctorsPanelProps {
  doctors: Doctor[];
  todayIso: string;
  tomorrowIso: string;
  dayFilter: 'all' | 'today' | 'tomorrow';
  searchQuery: string;
  highlightedSlots: Record<string, 'booked' | 'freed'>;
}

export function DoctorsPanel({
  doctors,
  todayIso,
  tomorrowIso,
  dayFilter,
  searchQuery,
  highlightedSlots,
}: DoctorsPanelProps) {
  const [specialty, setSpecialty] = useState<string>('All');

  const specialties = useMemo(
    () => ['All', ...Array.from(new Set(doctors.map((d) => d.specialty)))],
    [doctors]
  );

  const filteredDoctors = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    return doctors
      .filter((d) => specialty === 'All' || d.specialty === specialty)
      .filter(
        (d) =>
          !q ||
          d.name.toLowerCase().includes(q) ||
          d.specialty.toLowerCase().includes(q) ||
          d.room.toLowerCase().includes(q)
      )
      .map((d) => {
        const filteredSlots = d.slots.filter((s) => {
          if (dayFilter === 'today' && todayIso) return s.date === todayIso;
          if (dayFilter === 'tomorrow' && tomorrowIso) return s.date === tomorrowIso;
          return true;
        });
        return {
          ...d,
          slots: filteredSlots,
          available_count: filteredSlots.filter((s) => !s.is_booked).length,
        };
      });
  }, [doctors, specialty, dayFilter, todayIso, tomorrowIso, searchQuery]);

  return (
    <section className="left-ledger" aria-labelledby="physicians-heading">
      <h2 id="physicians-heading" className="sr-only">
        Physicians and availability
      </h2>

      <div className="specialty-ribbon" role="group" aria-label="Specialty filter">
        {specialties.map((spec) => (
          <button
            key={spec}
            type="button"
            className={`spec-tab ${specialty === spec ? 'active' : ''}`}
            onClick={() => setSpecialty(spec)}
          >
            {spec}
          </button>
        ))}
      </div>

      {filteredDoctors.length === 0 ? (
        <div className="quiet-empty">No matching physicians.</div>
      ) : (
        <div>
          {filteredDoctors.map((doc) => {
            const total = doc.slots.length;
            const ratio = total > 0 ? Math.round((doc.available_count / total) * 100) : 0;

            return (
              <article key={doc.id} className="physician-row">
                <div className="physician-meta">
                  <div className="physician-name">{doc.name}</div>
                  <div className="physician-sub">
                    {doc.specialty} · {doc.room}
                  </div>
                  <div className="capacity-bar" aria-label={`${doc.available_count} of ${total} open`}>
                    <div className="capacity-track">
                      <div className="capacity-fill" style={{ width: `${ratio}%` }} />
                    </div>
                    <span className="capacity-label mono">
                      {doc.available_count}/{total}
                    </span>
                  </div>
                </div>

                <div className="slot-matrix">
                  {doc.slots.map((slot) => {
                    const flash = highlightedSlots[slot.id];
                    const classes = [
                      'slot-tile',
                      'mono',
                      slot.is_booked ? 'booked' : '',
                      flash === 'booked' ? 'flash-booked' : '',
                      flash === 'freed' ? 'flash-freed' : '',
                    ]
                      .filter(Boolean)
                      .join(' ');

                    return (
                      <span
                        key={slot.id}
                        className={classes}
                        title={slot.is_booked ? 'Booked' : 'Open'}
                      >
                        <span className="slot-pip" aria-hidden="true" />
                        <span>{slot.time_display}</span>
                        {dayFilter === 'all' && (
                          <span className="slot-day-mini">
                            {formatDayLabel(slot.date, todayIso, tomorrowIso)}
                          </span>
                        )}
                      </span>
                    );
                  })}
                </div>
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}
