import { useEffect, useState } from 'react';
import { RefreshCw } from 'lucide-react';
import { clinicApi } from '../api/clinicApi';
import {
  CallSessionSummary,
  CallStatus,
  TranscriptEntryDTO,
  TranscriptItem,
} from '../types/clinic';

interface CallLogsViewProps {
  activeCallId: string | null;
  activeCallStatus: CallStatus;
  activeTranscript: TranscriptItem[];
  agentName: string;
}

function formatClock(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  } catch {
    return iso;
  }
}

export function CallLogsView({
  activeCallId,
  activeCallStatus,
  activeTranscript,
  agentName,
}: CallLogsViewProps) {
  const [calls, setCalls] = useState<CallSessionSummary[]>([]);
  const [selectedCallId, setSelectedCallId] = useState<string | null>(activeCallId);
  const [savedTranscript, setSavedTranscript] = useState<TranscriptEntryDTO[]>([]);
  const [loading, setLoading] = useState(false);

  const loadCalls = async (signal?: AbortSignal) => {
    setLoading(true);
    try {
      const list = await clinicApi.listCalls(signal);
      setCalls(list);
      setSelectedCallId((prev) => prev ?? activeCallId ?? list[0]?.call_id ?? null);
    } catch {
      // Ignore abort
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    const controller = new AbortController();
    void loadCalls(controller.signal);
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeCallId, activeCallStatus]);

  useEffect(() => {
    if (activeCallId && (activeCallStatus === 'ringing' || activeCallStatus === 'connected')) {
      setSelectedCallId(activeCallId);
    }
  }, [activeCallId, activeCallStatus]);

  const viewingLive =
    selectedCallId !== null &&
    selectedCallId === activeCallId &&
    (activeCallStatus === 'ringing' || activeCallStatus === 'connected');

  useEffect(() => {
    if (!selectedCallId || viewingLive) {
      setSavedTranscript([]);
      return;
    }
    const controller = new AbortController();
    clinicApi
      .getCallTranscript(selectedCallId, controller.signal)
      .then((entries) => setSavedTranscript(entries))
      .catch(() => setSavedTranscript([]));
    return () => controller.abort();
  }, [selectedCallId, viewingLive]);

  const selected = calls.find((c) => c.call_id === selectedCallId) ?? null;

  return (
    <div className="calls-split">
      <section className="calls-list-col" aria-labelledby="calls-heading">
        <div className="section-bar">
          <h2 id="calls-heading" className="section-label">
            Sessions
          </h2>
          <button
            type="button"
            className="icon-btn"
            style={{ width: 26, height: 26 }}
            onClick={() => void loadCalls()}
            disabled={loading}
            aria-label="Refresh sessions"
          >
            <RefreshCw size={12} />
          </button>
        </div>

        {calls.length === 0 ? (
          <div className="quiet-empty">No calls recorded.</div>
        ) : (
          <div role="listbox" aria-label="Voice calls">
            {calls.map((session) => {
              const isSelected = session.call_id === selectedCallId;
              const outcome = session.outcome ?? session.state;
              return (
                <button
                  key={session.call_id}
                  type="button"
                  role="option"
                  aria-selected={isSelected}
                  className={`call-row-btn ${isSelected ? 'selected' : ''}`}
                  onClick={() => setSelectedCallId(session.call_id)}
                >
                  <div className="call-row-top">
                    <span className="call-row-id mono">{session.call_id}</span>
                    <span className={`call-row-outcome mono ${outcome}`}>{outcome}</span>
                  </div>
                  <div className="call-row-sub mono">
                    <span>{session.caller_phone ?? '—'}</span>
                    <span>{formatClock(session.created_at)}</span>
                  </div>
                  <div className="call-row-sub mono">
                    <span>
                      {session.turns_count} turns · {session.tool_calls_count} tools
                    </span>
                    {session.avg_llm_ttft_ms !== null && (
                      <span>{session.avg_llm_ttft_ms}ms</span>
                    )}
                  </div>
                </button>
              );
            })}
          </div>
        )}
      </section>

      <section className="calls-detail-col" aria-labelledby="inspector-heading">
        <div className="section-bar">
          <h2 id="inspector-heading" className="section-label">
            {selectedCallId ? selectedCallId : 'Transcript'}
          </h2>
          <span className="section-count mono">
            {viewingLive
              ? 'Live'
              : selected?.avg_llm_ttft_ms !== null && selected?.avg_llm_ttft_ms !== undefined
                ? `Avg ${selected.avg_llm_ttft_ms}ms`
                : ''}
          </span>
        </div>

        <div className="feed-stream tall" aria-live="polite">
          {viewingLive ? (
            activeTranscript.length === 0 ? (
              <div className="quiet-empty">Listening…</div>
            ) : (
              activeTranscript.map((item) => {
                const isTool = item.role !== 'caller' && item.role !== 'agent';
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
                          : item.role}
                    </span>
                    <span className={`feed-text ${isTool ? 'mono' : ''}`}>
                      {item.text}
                      {item.latencyMs !== null && item.latencyMs !== undefined && (
                        <span className="latency-tag mono">{item.latencyMs}ms</span>
                      )}
                    </span>
                  </div>
                );
              })
            )
          ) : savedTranscript.length === 0 ? (
            <div className="quiet-empty">
              {selectedCallId ? 'No turns recorded.' : 'Select a session.'}
            </div>
          ) : (
            savedTranscript.map((entry) => {
              const isTool = entry.role !== 'caller' && entry.role !== 'agent';
              return (
                <div
                  key={entry.id}
                  className={`feed-entry ${entry.role === 'caller' ? 'caller' : isTool ? 'tool' : ''}`}
                >
                  <span className="feed-who mono">
                    {entry.role === 'caller'
                      ? 'Caller'
                      : entry.role === 'agent'
                        ? agentName
                        : entry.role}
                  </span>
                  <span className={`feed-text ${isTool ? 'mono' : ''}`}>
                    {entry.text}
                    {entry.latency_ms !== null && (
                      <span className="latency-tag mono">{entry.latency_ms}ms</span>
                    )}
                  </span>
                </div>
              );
            })
          )}
        </div>
      </section>
    </div>
  );
}
