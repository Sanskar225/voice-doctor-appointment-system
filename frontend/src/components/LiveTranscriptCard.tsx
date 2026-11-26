import { useEffect, useRef } from 'react';
import { CallStatus, TranscriptItem } from '../types/clinic';

interface LiveTranscriptCardProps {
  callId: string | null;
  callStatus: CallStatus;
  agentName: string;
  verifiedPhone: string | null;
  transcript: TranscriptItem[];
}

export function LiveTranscriptCard({
  callId,
  callStatus,
  agentName,
  verifiedPhone,
  transcript,
}: LiveTranscriptCardProps) {
  const scrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [transcript]);

  const metaText =
    callStatus === 'connected'
      ? verifiedPhone ?? callId ?? 'Live'
      : callStatus === 'ringing'
        ? 'Dialing'
        : callStatus === 'ended'
          ? 'Ended'
          : 'Idle';

  return (
    <section className="live-feed-box" aria-labelledby="transcript-heading">
      <div className="section-bar">
        <h2 id="transcript-heading" className="section-label">
          Transcript
        </h2>
        <span className="section-count mono">{metaText}</span>
      </div>

      <div ref={scrollRef} className="feed-stream" aria-live="polite">
        {transcript.length === 0 ? (
          <div className="quiet-empty">
            {callStatus === 'connected' ? 'Listening…' : 'Start a call to view live transcript.'}
          </div>
        ) : (
          transcript.map((item) => {
            const isTool = item.role === 'tool' || item.role === 'booking' || item.role === 'cancellation';
            return (
              <div
                key={item.id}
                className={`feed-entry ${item.role === 'caller' ? 'caller' : isTool ? 'tool' : ''}`}
              >
                <span className="feed-who mono">
                  {item.role === 'caller'
                    ? 'Caller'
                    : item.role === 'agent'
                      ? agentName
                      : item.role === 'booking'
                        ? 'Booked'
                        : item.role === 'cancellation'
                          ? 'Cancelled'
                          : 'Tool'}
                </span>
                <span className={`feed-text ${isTool ? 'mono' : ''}`}>
                  {item.role === 'booking' || item.role === 'cancellation'
                    ? item.appointment
                      ? `${item.appointment.doctor_name} · ${item.appointment.time_display} (${item.appointment.reference_code})`
                      : item.text
                    : item.text}
                  {item.latencyMs !== null && item.latencyMs !== undefined && (
                    <span className="latency-tag mono">{item.latencyMs}ms</span>
                  )}
                </span>
              </div>
            );
          })
        )}
      </div>
    </section>
  );
}
