import { useCallback, useMemo, useState } from 'react';
import { AlertTriangle, Search } from 'lucide-react';
import { AgentView } from './components/AgentView';
import { AppointmentsPanel } from './components/AppointmentsPanel';
import { CallLogsView } from './components/CallLogsView';
import { DoctorsPanel } from './components/DoctorsPanel';
import { LiveTranscriptCard } from './components/LiveTranscriptCard';
import { Masthead } from './components/Masthead';
import { PhoneCallSheet } from './components/PhoneCallSheet';
import { useClinicSync } from './hooks/useClinicSync';
import { useVoiceCall } from './hooks/useVoiceCall';
import { NavTab } from './types/clinic';

function formatEditorialDate(isoDate: string): string {
  if (!isoDate) return 'Schedule';
  const [y, m, d] = isoDate.split('-').map(Number);
  if (!y || !m || !d) return isoDate;
  const dt = new Date(y, m - 1, d);
  return dt.toLocaleDateString('en-US', {
    weekday: 'long',
    day: 'numeric',
    month: 'short',
  });
}

export default function App() {
  const { state, resetting, resetDemo, saveConfig, cancelFromDesk } = useClinicSync();
  const voice = useVoiceCall();

  const [activeTab, setActiveTab] = useState<NavTab>('desk');
  const [dayFilter, setDayFilter] = useState<'all' | 'today' | 'tomorrow'>('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [phoneOpen, setPhoneOpen] = useState(false);

  const openSlots = useMemo(
    () => state.doctors.reduce((acc, doc) => acc + doc.available_count, 0),
    [state.doctors]
  );
  const confirmedCount = useMemo(
    () => state.appointments.filter((a) => a.status === 'confirmed').length,
    [state.appointments]
  );

  const displayDate = useMemo(() => {
    if (dayFilter === 'tomorrow' && state.tomorrow) return formatEditorialDate(state.tomorrow);
    if (state.today) return formatEditorialDate(state.today);
    return 'Schedule';
  }, [dayFilter, state.today, state.tomorrow]);

  const handleTryCall = useCallback(() => {
    setPhoneOpen(true);
    if (voice.status === 'idle' || voice.status === 'ended') {
      void voice.startCall();
    }
  }, [voice]);

  const handleRedial = useCallback(() => {
    void voice.startCall();
  }, [voice]);

  const handleClosePhone = useCallback(() => {
    if (voice.status === 'connected' || voice.status === 'ringing') {
      voice.endCall();
    }
    setPhoneOpen(false);
  }, [voice]);

  return (
    <div className="page-shell">
      <Masthead
        clinicName={state.config.clinic_name}
        activeTab={activeTab}
        onSelectTab={setActiveTab}
        health={state.health}
        streamStatus={state.streamStatus}
        callStatus={voice.status}
        elapsedSeconds={voice.elapsedSeconds}
        onTryCall={handleTryCall}
        onReset={resetDemo}
        resetting={resetting}
      />

      <main className="canvas">
        {state.health && !state.health.voice_ready && (
          <div className="setup-strip" role="status">
            <AlertTriangle size={14} />
            <span>
              Set <strong className="mono">{state.health.missing_keys.join(', ')}</strong> in{' '}
              <code className="mono">.env</code> to enable voice calls.
            </span>
          </div>
        )}

        {activeTab === 'desk' && (
          <>
            <div className="schedule-masthead">
              <div className="date-cluster">
                <h1 className="date-display">{displayDate}</h1>
                <div className="ratio-meta mono">
                  <span>
                    <strong>{openSlots}</strong> open
                  </span>
                  <span>·</span>
                  <span>
                    <strong>{confirmedCount}</strong> booked
                  </span>
                </div>
              </div>

              <div className="schedule-controls">
                <div className="day-switch" role="group" aria-label="Day filter">
                  {(['all', 'today', 'tomorrow'] as const).map((day) => (
                    <button
                      key={day}
                      type="button"
                      className={`day-btn ${dayFilter === day ? 'active' : ''}`}
                      onClick={() => setDayFilter(day)}
                    >
                      {day === 'all' ? 'All' : day === 'today' ? 'Today' : 'Tomorrow'}
                    </button>
                  ))}
                </div>

                <div className="filter-search">
                  <Search size={13} className="filter-search-icon" />
                  <input
                    type="search"
                    placeholder="Search…"
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    aria-label="Search doctor or phone"
                  />
                </div>
              </div>
            </div>

            <div className="editorial-split">
              <DoctorsPanel
                doctors={state.doctors}
                todayIso={state.today}
                tomorrowIso={state.tomorrow}
                dayFilter={dayFilter}
                searchQuery={searchQuery}
                highlightedSlots={state.highlightedSlots}
              />

              <div className="right-ledger">
                <AppointmentsPanel
                  appointments={state.appointments}
                  searchQuery={searchQuery}
                  highlightedRows={state.highlightedRows}
                  onCancelAppointment={cancelFromDesk}
                />
                <LiveTranscriptCard
                  callId={voice.callId}
                  callStatus={voice.status}
                  agentName={state.config.agent_name}
                  verifiedPhone={voice.verifiedPhone}
                  transcript={voice.transcript}
                />
              </div>
            </div>
          </>
        )}

        {activeTab === 'calls' && (
          <CallLogsView
            activeCallId={voice.callId}
            activeCallStatus={voice.status}
            activeTranscript={voice.transcript}
            agentName={state.config.agent_name}
          />
        )}

        {activeTab === 'agent' && (
          <AgentView
            config={state.config}
            callStatus={voice.status}
            activeStage={voice.pipelineStage}
            stageDetail={voice.pipelineDetail}
            metrics={voice.metrics}
            llmModel={state.health?.llm_model ?? 'gemini-2.5-flash'}
            onSaveConfig={saveConfig}
          />
        )}
      </main>

      <PhoneCallSheet
        open={phoneOpen}
        clinicName={state.config.clinic_name}
        agentName={state.config.agent_name}
        callId={voice.callId}
        status={voice.status}
        muted={voice.muted}
        elapsedSeconds={voice.elapsedSeconds}
        activeSpeaker={voice.activeSpeaker}
        verifiedPhone={voice.verifiedPhone}
        waveform={voice.waveform}
        transcript={voice.transcript}
        error={voice.error}
        onClose={handleClosePhone}
        onEndCall={voice.endCall}
        onToggleMute={voice.toggleMute}
        onRedial={handleRedial}
      />
    </div>
  );
}
