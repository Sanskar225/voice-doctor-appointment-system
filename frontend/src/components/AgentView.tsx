import { FormEvent, useEffect, useState } from 'react';
import { Check } from 'lucide-react';
import {
  CallLatencyMetrics,
  CallStatus,
  ClinicConfig,
  PipelineStage,
  UpdateClinicConfig,
} from '../types/clinic';

interface AgentViewProps {
  config: ClinicConfig;
  callStatus: CallStatus;
  activeStage: PipelineStage;
  stageDetail: string;
  metrics: CallLatencyMetrics;
  llmModel: string;
  onSaveConfig: (patch: UpdateClinicConfig) => Promise<ClinicConfig>;
}

const STAGES: Array<{
  id: PipelineStage | 'mic';
  idx: string;
  title: string;
  spec: string;
}> = [
  { id: 'mic', idx: '01', title: 'Audio In', spec: '16 kHz PCM WS' },
  { id: 'vad', idx: '02', title: 'Silero VAD', spec: 'Turn & Barge-in' },
  { id: 'stt', idx: '03', title: 'ElevenLabs STT', spec: 'Scribe v2' },
  { id: 'llm', idx: '04', title: 'Gemini', spec: 'thinking=0' },
  { id: 'tool', idx: '05', title: 'Tools', spec: 'SQLite WAL' },
  { id: 'tts', idx: '06', title: 'ElevenLabs TTS', spec: 'Flash v2.5' },
];

const TOOLS = [
  {
    name: 'check_doctor_availability',
    note: 'Open slots by doctor, specialty, or date',
    rule: 'Read-only',
  },
  {
    name: 'book_appointment',
    note: 'Atomic slot reservation & overlap check',
    rule: 'Phone read-back required · No-cancel',
  },
  {
    name: 'cancel_appointment',
    note: 'Phone lookup, disambiguation & slot reopen',
    rule: 'Phone read-back required · No-cancel',
  },
];

export function AgentView({
  config,
  callStatus,
  activeStage,
  stageDetail,
  metrics,
  llmModel,
  onSaveConfig,
}: AgentViewProps) {
  const [clinicName, setClinicName] = useState(config.clinic_name);
  const [agentName, setAgentName] = useState(config.agent_name);
  const [tone, setTone] = useState<'warm' | 'formal'>(config.greeting_tone);
  const [ttsSpeed, setTtsSpeed] = useState(config.tts_speed);
  const [strictReadback, setStrictReadback] = useState(config.strict_phone_readback);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    setClinicName(config.clinic_name);
    setAgentName(config.agent_name);
    setTone(config.greeting_tone);
    setTtsSpeed(config.tts_speed);
    setStrictReadback(config.strict_phone_readback);
  }, [config]);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setSaved(false);
    try {
      await onSaveConfig({
        clinic_name: clinicName.trim() || 'Aurelia',
        agent_name: agentName.trim() || 'Maya',
        greeting_tone: tone,
        tts_speed: ttsSpeed,
        strict_phone_readback: strictReadback,
      });
      setSaved(true);
      window.setTimeout(() => setSaved(false), 2200);
    } finally {
      setSaving(false);
    }
  };

  const isConnected = callStatus === 'connected';

  return (
    <div>
      <div className="section-bar">
        <h2 className="section-label">Pipecat Signal Chain</h2>
        <span className="section-count mono">
          {llmModel}
          {metrics.llmTtftMs !== null ? ` · TTFT ${metrics.llmTtftMs}ms` : ''}
          {metrics.toolExecMs !== null ? ` · Tool ${metrics.toolExecMs}ms` : ''}
          {isConnected ? ` · ${stageDetail}` : ''}
        </span>
      </div>

      <div className="signal-chain">
        {STAGES.map((stage) => {
          const lit =
            (stage.id === 'mic' && isConnected) ||
            (isConnected && activeStage === stage.id);

          return (
            <div key={stage.id} className={`signal-node ${lit ? 'lit' : ''}`}>
              <span className="signal-idx mono">{stage.idx}</span>
              <span className="signal-title">{stage.title}</span>
              <span className="signal-spec mono">{stage.spec}</span>
            </div>
          );
        })}
      </div>

      <div className="agent-split">
        <section className="agent-form-col" aria-labelledby="config-heading">
          <div className="section-bar" style={{ paddingTop: 0 }}>
            <h2 id="config-heading" className="section-label">
              Deployment Config
            </h2>
            <span className="section-count mono">Live</span>
          </div>

          <form className="minimal-form" onSubmit={handleSubmit}>
            <div className="form-grid-2">
              <label className="f-label">
                <span>Clinic</span>
                <input
                  type="text"
                  className="f-input"
                  value={clinicName}
                  onChange={(e) => setClinicName(e.target.value)}
                  minLength={2}
                  maxLength={60}
                  required
                />
              </label>

              <label className="f-label">
                <span>Receptionist</span>
                <input
                  type="text"
                  className="f-input"
                  value={agentName}
                  onChange={(e) => setAgentName(e.target.value)}
                  minLength={2}
                  maxLength={32}
                  required
                />
              </label>
            </div>

            <div className="form-grid-2">
              <div className="f-label">
                <span>Tone</span>
                <div className="day-switch" style={{ width: 'fit-content' }}>
                  <button
                    type="button"
                    className={`day-btn ${tone === 'warm' ? 'active' : ''}`}
                    onClick={() => setTone('warm')}
                  >
                    Warm
                  </button>
                  <button
                    type="button"
                    className={`day-btn ${tone === 'formal' ? 'active' : ''}`}
                    onClick={() => setTone('formal')}
                  >
                    Formal
                  </button>
                </div>
              </div>

              <label className="f-label">
                <span>
                  Cadence <span className="mono">{ttsSpeed.toFixed(2)}x</span>
                </span>
                <input
                  type="range"
                  min={0.85}
                  max={1.15}
                  step={0.01}
                  value={ttsSpeed}
                  onChange={(e) => setTtsSpeed(parseFloat(e.target.value))}
                  className="f-range"
                />
              </label>
            </div>

            <label className="f-check">
              <input
                type="checkbox"
                checked={strictReadback}
                onChange={(e) => setStrictReadback(e.target.checked)}
              />
              <span>Enforce phone read-back state machine</span>
            </label>

            <button type="submit" className="f-save" disabled={saving}>
              {saved ? (
                <>
                  <Check size={14} />
                  <span>Saved</span>
                </>
              ) : saving ? (
                <span>Saving…</span>
              ) : (
                <span>Apply</span>
              )}
            </button>
          </form>
        </section>

        <section className="agent-tools-col" aria-labelledby="tools-heading">
          <div className="section-bar" style={{ paddingTop: 0 }}>
            <h2 id="tools-heading" className="section-label">
              Tools
            </h2>
            <span className="section-count mono">3</span>
          </div>

          <div>
            {TOOLS.map((tool) => (
              <div key={tool.name} className="tool-line-item">
                <span className="tool-code mono">{tool.name}()</span>
                <span className="tool-note">{tool.note}</span>
                <span className="tool-rule mono">{tool.rule}</span>
              </div>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}
