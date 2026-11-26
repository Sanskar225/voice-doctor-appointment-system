import { Phone, RotateCcw } from 'lucide-react';
import { CallStatus, HealthStatus, NavTab, StreamStatus } from '../types/clinic';

interface MastheadProps {
  clinicName: string;
  activeTab: NavTab;
  onSelectTab: (tab: NavTab) => void;
  health: HealthStatus | null;
  streamStatus: StreamStatus;
  callStatus: CallStatus;
  elapsedSeconds: number;
  onTryCall: () => void;
  onReset: () => void;
  resetting: boolean;
}

function formatTimer(totalSeconds: number): string {
  const mins = Math.floor(totalSeconds / 60);
  const secs = totalSeconds % 60;
  return `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
}

export function Masthead({
  clinicName,
  activeTab,
  onSelectTab,
  health,
  streamStatus,
  callStatus,
  elapsedSeconds,
  onTryCall,
  onReset,
  resetting,
}: MastheadProps) {
  const isCallLive = callStatus === 'ringing' || callStatus === 'connected';
  const online = Boolean(health?.voice_ready) && streamStatus === 'live';

  const statusText = !health
    ? 'Offline'
    : streamStatus === 'reconnecting'
      ? 'Syncing'
      : health.voice_ready
        ? 'Live'
        : 'Setup';

  return (
    <header className="masthead">
      <div className="masthead-inner">
        <div className="brand-mark-wrap">
          <span className="brand-wordmark">{clinicName}</span>
          <span className="live-tag mono" title={health?.llm_model ?? ''}>
            <span className={`live-dot ${online ? '' : 'warn'}`} />
            <span>{statusText}</span>
          </span>
        </div>

        <nav className="nav-tabs" aria-label="Primary">
          <button
            type="button"
            className={`nav-tab ${activeTab === 'desk' ? 'active' : ''}`}
            onClick={() => onSelectTab('desk')}
          >
            Schedule
          </button>
          <button
            type="button"
            className={`nav-tab ${activeTab === 'calls' ? 'active' : ''}`}
            onClick={() => onSelectTab('calls')}
          >
            <span>Calls</span>
            {isCallLive && <span className="tab-pulse-dot" aria-label="Call active" />}
          </button>
          <button
            type="button"
            className={`nav-tab ${activeTab === 'agent' ? 'active' : ''}`}
            onClick={() => onSelectTab('agent')}
          >
            Agent
          </button>
        </nav>

        <div className="masthead-right">
          <button
            type="button"
            className="icon-btn"
            onClick={onReset}
            disabled={resetting}
            aria-label="Reset schedule"
            title="Reset schedule"
          >
            <RotateCcw size={14} />
          </button>

          <button
            type="button"
            className={`call-trigger ${isCallLive ? 'live' : ''}`}
            onClick={onTryCall}
          >
            {isCallLive ? (
              <>
                <span className="trigger-ping" aria-hidden="true" />
                <span className="mono">
                  {callStatus === 'ringing' ? 'Dialing…' : formatTimer(elapsedSeconds)}
                </span>
              </>
            ) : (
              <>
                <Phone size={14} />
                <span>Try Call</span>
              </>
            )}
          </button>
        </div>
      </div>
    </header>
  );
}
