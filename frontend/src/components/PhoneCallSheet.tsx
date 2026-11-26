import { useEffect, useRef } from 'react';
import {
  CheckCircle2,
  Loader2,
  Mic,
  MicOff,
  Phone,
  PhoneOff,
  ShieldCheck,
  X,
  XCircle,
} from 'lucide-react';
import { CallStatus, TranscriptItem } from '../types/clinic';

interface PhoneCallSheetProps {
  open: boolean;
  clinicName: string;
  agentName: string;
  callId: string | null;
  status: CallStatus;
  muted: boolean;
  elapsedSeconds: number;
  activeSpeaker: 'none' | 'user' | 'agent';
  verifiedPhone: string | null;
  waveform: number[];
  transcript: TranscriptItem[];
  error: string | null;
  onClose: () => void;
  onEndCall: () => void;
  onToggleMute: () => void;
  onRedial: () => void;
}

let cachedDisplayTransitionSupport: boolean | undefined;

function canTransitionDisplay(): boolean {
  if (cachedDisplayTransitionSupport !== undefined) {
    return cachedDisplayTransitionSupport;
  }
  if (!window.CSS?.supports?.('transition-behavior', 'allow-discrete') || !document.body) {
    return false;
  }
  const probe = document.createElement('div');
  probe.style.cssText = 'transition: display 1s allow-discrete !important; display: block;';
  document.body.appendChild(probe);
  getComputedStyle(probe).display;
  probe.style.display = 'none';
  cachedDisplayTransitionSupport = getComputedStyle(probe).display === 'block';
  probe.remove();
  return cachedDisplayTransitionSupport;
}

function supportsTopLayerExit(): boolean {
  return Boolean(window.CSS?.supports?.('overlay', 'auto') && canTransitionDisplay());
}

async function closeDialogSmoothly(dialog: HTMLDialogElement): Promise<void> {
  if (!dialog.open) return;
  if (!supportsTopLayerExit()) {
    dialog.setAttribute('data-closing', '');
    const animations = dialog.getAnimations({ subtree: true });
    if (animations.length > 0) {
      await Promise.race([
        Promise.allSettled(animations.map((a) => a.finished)),
        new Promise((r) => window.setTimeout(r, 400)),
      ]);
    }
    if (!dialog.hasAttribute('data-closing')) return;
    dialog.removeAttribute('data-closing');
  }
  dialog.close();
}

function formatTimer(totalSeconds: number): string {
  const mins = Math.floor(totalSeconds / 60);
  const secs = totalSeconds % 60;
  return `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
}

export function PhoneCallSheet({
  open,
  clinicName,
  agentName,
  callId,
  status,
  muted,
  elapsedSeconds,
  activeSpeaker,
  verifiedPhone,
  waveform,
  transcript,
  error,
  onClose,
  onEndCall,
  onToggleMute,
  onRedial,
}: PhoneCallSheetProps) {
  const dialogRef = useRef<HTMLDialogElement | null>(null);
  const feedRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;

    if (open && !dialog.open) {
      dialog.removeAttribute('data-closing');
      dialog.show();
    } else if (!open && dialog.open) {
      void closeDialogSmoothly(dialog);
    }
  }, [open]);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    const handleCancel = (e: Event) => {
      e.preventDefault();
      onClose();
    };
    dialog.addEventListener('cancel', handleCancel);
    return () => dialog.removeEventListener('cancel', handleCancel);
  }, [onClose]);

  useEffect(() => {
    if (feedRef.current) {
      feedRef.current.scrollTop = feedRef.current.scrollHeight;
    }
  }, [transcript]);

  const initial = (agentName.trim()[0] ?? 'M').toUpperCase();
  const speakerState =
    status !== 'connected'
      ? 'Ended'
      : muted
        ? 'Muted'
        : activeSpeaker === 'agent'
          ? agentName
          : activeSpeaker === 'user'
            ? 'You'
            : 'Listening';

  const turnCount = transcript.filter((t) => t.role === 'caller' || t.role === 'agent').length;

  return (
    <dialog
      ref={dialogRef}
      className="phone-dialog"
      aria-label={`Voice call with ${clinicName}`}
    >
      <div className="handset">
        <div className="handset-top">
          <span className="mono">{clinicName}</span>
          <div className="speaker-notch mono" aria-hidden="true">
            <span
              className={`notch-dot ${
                status === 'ringing' ? 'dialing' : status === 'ended' ? 'off' : ''
              }`}
            />
            <span>{status === 'connected' ? '16kHz' : status === 'ringing' ? 'Dialing' : 'Ended'}</span>
          </div>
          <button
            type="button"
            className="handset-x"
            onClick={onClose}
            aria-label="Close"
            title="Close"
          >
            <X size={13} />
          </button>
        </div>

        {status === 'ringing' ? (
          <div className="dialing-view">
            <div className="sonar-stage" aria-hidden="true">
              <span className="sonar-pulse" />
              <span className="sonar-pulse second" />
              <div className="sonar-monogram">{initial}</div>
            </div>
            <div>
              <div className="dialing-name">{agentName}</div>
              <div className="dialing-label mono">Calling {clinicName}…</div>
            </div>
          </div>
        ) : (
          <>
            <div className="callee-bar">
              <div className="callee-left">
                <div className="callee-badge" aria-hidden="true">
                  {initial}
                </div>
                <div>
                  <div className="callee-title">{agentName}</div>
                  <div className="callee-clock mono">
                    {status === 'connected' ? formatTimer(elapsedSeconds) : 'Call Ended'}
                    {callId ? ` · ${callId}` : ''}
                  </div>
                </div>
              </div>

              {verifiedPhone && (
                <span className="verified-chip mono" title="Verified phone">
                  <ShieldCheck size={11} />
                  <span>{verifiedPhone}</span>
                </span>
              )}
            </div>

            <div className="spectrum-band">
              <div className="spectrum-bars" aria-hidden="true">
                {waveform.map((level, idx) => (
                  <span
                    key={idx}
                    className={`spectrum-bar ${
                      muted ? 'muted' : activeSpeaker === 'user' ? 'user' : ''
                    }`}
                    style={{ height: `${Math.round(Math.max(4, level * 34))}px` }}
                  />
                ))}
              </div>
              <span className="spectrum-state">{speakerState}</span>
            </div>

            <div ref={feedRef} className="handset-scroll" aria-live="polite">
              {transcript.length === 0 ? (
                <div className="handset-empty">
                  <div>{status === 'connected' ? 'Speak to book or cancel.' : 'Call ended.'}</div>
                  {status === 'connected' && (
                    <div className="say-prompt">“Check Dr. Mehta today”</div>
                  )}
                </div>
              ) : (
                transcript.map((item) => {
                  if (item.role === 'tool') {
                    return (
                      <div key={item.id} className="tool-pill-dark mono">
                        <Loader2 size={11} />
                        <span>{item.text}</span>
                      </div>
                    );
                  }

                  if (
                    (item.role === 'booking' || item.role === 'cancellation') &&
                    item.appointment
                  ) {
                    const isCancel = item.role === 'cancellation';
                    return (
                      <div
                        key={item.id}
                        className={`ticket-card ${isCancel ? 'cancelled' : ''}`}
                      >
                        <div className="ticket-head">
                          <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.32rem' }}>
                            {isCancel ? <XCircle size={13} /> : <CheckCircle2 size={13} />}
                            {isCancel ? 'Cancelled' : 'Confirmed'}
                          </span>
                          <span className="mono">{item.appointment.reference_code}</span>
                        </div>
                        <div className="ticket-body">
                          <div className="ticket-doc">{item.appointment.doctor_name}</div>
                          <div className="ticket-row">
                            <span>{item.appointment.doctor_specialty}</span>
                            <span className="mono">
                              {item.appointment.date} · {item.appointment.time_display}
                            </span>
                          </div>
                          <div className="ticket-row">
                            <span>Phone</span>
                            <span className="mono">{item.appointment.caller_phone_display}</span>
                          </div>
                        </div>
                      </div>
                    );
                  }

                  return (
                    <div key={item.id} className={`turn-bubble ${item.role}`}>
                      <div className="turn-who">{item.role === 'agent' ? agentName : 'You'}</div>
                      <div>{item.text}</div>
                    </div>
                  );
                })
              )}
            </div>

            {status === 'ended' && turnCount > 0 && (
              <div className="ended-bar mono">
                <span>{formatTimer(elapsedSeconds)}</span>
                <span>{turnCount} turns</span>
              </div>
            )}
          </>
        )}

        {error && <div className="handset-err">{error}</div>}

        <div className="handset-keys">
          {status === 'ringing' ? (
            <button
              type="button"
              className="hw-key hangup"
              onClick={onEndCall}
              aria-label="Cancel call"
            >
              <PhoneOff size={21} />
            </button>
          ) : status === 'connected' ? (
            <>
              <button
                type="button"
                className={`hw-key mute ${muted ? 'active' : ''}`}
                onClick={onToggleMute}
                aria-label={muted ? 'Unmute' : 'Mute'}
                title={muted ? 'Unmute' : 'Mute'}
              >
                {muted ? <MicOff size={18} /> : <Mic size={18} />}
              </button>

              <button
                type="button"
                className="hw-key hangup"
                onClick={onEndCall}
                aria-label="End call"
                title="End call"
              >
                <PhoneOff size={21} />
              </button>
            </>
          ) : (
            <button type="button" className="hw-key call-again" onClick={onRedial}>
              <Phone size={14} />
              <span>Call Again</span>
            </button>
          )}
        </div>
      </div>
    </dialog>
  );
}
