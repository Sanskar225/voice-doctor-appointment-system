import { useCallback, useEffect, useRef, useState } from 'react';
import { clinicApi } from '../api/clinicApi';
import {
  Appointment,
  CallLatencyMetrics,
  CallStatus,
  EventEnvelope,
  PipelineStage,
  TranscriptItem,
} from '../types/clinic';
import { callSounds } from '../utils/soundEffects';

const SAMPLE_RATE = 16000;
const WAVEFORM_BARS = 28;
const MAX_WS_BUFFERED_BYTES = 65536;

const INITIAL_METRICS: CallLatencyMetrics = {
  llmTtftMs: null,
  avgLlmTtftMs: null,
  toolExecMs: null,
  lastTool: null,
};

export interface VoiceCallController {
  callId: string | null;
  status: CallStatus;
  muted: boolean;
  elapsedSeconds: number;
  activeSpeaker: 'none' | 'user' | 'agent';
  pipelineStage: PipelineStage;
  pipelineDetail: string;
  verifiedPhone: string | null;
  metrics: CallLatencyMetrics;
  waveform: number[];
  transcript: TranscriptItem[];
  error: string | null;
  startCall: () => Promise<void>;
  endCall: () => void;
  toggleMute: () => void;
}

export function useVoiceCall(): VoiceCallController {
  const [callId, setCallId] = useState<string | null>(null);
  const [status, setStatus] = useState<CallStatus>('idle');
  const [muted, setMuted] = useState(false);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [activeSpeaker, setActiveSpeaker] = useState<'none' | 'user' | 'agent'>('none');
  const [pipelineStage, setPipelineStage] = useState<PipelineStage>('idle');
  const [pipelineDetail, setPipelineDetail] = useState<string>('Standby');
  const [verifiedPhone, setVerifiedPhone] = useState<string | null>(null);
  const [metrics, setMetrics] = useState<CallLatencyMetrics>(INITIAL_METRICS);
  const [waveform, setWaveform] = useState<number[]>(() => Array(WAVEFORM_BARS).fill(0.07));
  const [transcript, setTranscript] = useState<TranscriptItem[]>([]);
  const [error, setError] = useState<string | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const callEventsRef = useRef<EventSource | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const captureCtxRef = useRef<AudioContext | null>(null);
  const sourceNodeRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const micAnalyserRef = useRef<AnalyserNode | null>(null);
  const workletNodeRef = useRef<AudioWorkletNode | null>(null);
  const silentGainRef = useRef<GainNode | null>(null);

  const playbackCtxRef = useRef<AudioContext | null>(null);
  const playbackAnalyserRef = useRef<AnalyserNode | null>(null);
  const nextPlayTimeRef = useRef<number>(0);
  const activeSourcesRef = useRef<Set<AudioBufferSourceNode>>(new Set());

  const mutedRef = useRef(false);
  const rafRef = useRef<number | null>(null);
  const timerRef = useRef<number | null>(null);
  const ringTimeoutRef = useRef<number | null>(null);
  const attemptSeqRef = useRef(0);

  useEffect(() => {
    mutedRef.current = muted;
  }, [muted]);

  const stopWaveformLoop = useCallback(() => {
    if (rafRef.current !== null) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }
    setWaveform(Array(WAVEFORM_BARS).fill(0.07));
  }, []);

  const startWaveformLoop = useCallback(() => {
    stopWaveformLoop();
    const micBins = new Uint8Array(64);
    const agentBins = new Uint8Array(64);

    const tick = () => {
      const micAnalyser = micAnalyserRef.current;
      const agentAnalyser = playbackAnalyserRef.current;

      let micHasSignal = false;
      let agentHasSignal = false;

      if (micAnalyser && !mutedRef.current) {
        micAnalyser.getByteFrequencyData(micBins);
        for (let i = 1; i < 32; i++) {
          if (micBins[i] > 14) {
            micHasSignal = true;
            break;
          }
        }
      } else {
        micBins.fill(0);
      }

      if (agentAnalyser) {
        agentAnalyser.getByteFrequencyData(agentBins);
        for (let i = 1; i < 32; i++) {
          if (agentBins[i] > 10) {
            agentHasSignal = true;
            break;
          }
        }
      } else {
        agentBins.fill(0);
      }

      const half = WAVEFORM_BARS / 2;
      const bars = new Array<number>(WAVEFORM_BARS);
      for (let i = 0; i < half; i++) {
        const binIdx = Math.min(31, 2 + i * 2);
        const raw = agentHasSignal
          ? agentBins[binIdx] / 255
          : micHasSignal
            ? micBins[binIdx] / 255
            : 0;
        const shaped = Math.min(1, Math.max(0.07, 0.07 + Math.pow(raw, 0.85) * 0.95));
        bars[half - 1 - i] = shaped;
        bars[half + i] = shaped;
      }

      setWaveform(bars);
      rafRef.current = requestAnimationFrame(tick);
    };

    rafRef.current = requestAnimationFrame(tick);
  }, [stopWaveformLoop]);

  const flushPlayback = useCallback(() => {
    for (const source of activeSourcesRef.current) {
      try {
        source.stop();
      } catch {
        // Already stopped
      }
    }
    activeSourcesRef.current.clear();
    if (playbackCtxRef.current) {
      nextPlayTimeRef.current = playbackCtxRef.current.currentTime;
    }
  }, []);

  const cleanupResources = useCallback(() => {
    callSounds.stopRing();

    if (ringTimeoutRef.current !== null) {
      window.clearTimeout(ringTimeoutRef.current);
      ringTimeoutRef.current = null;
    }
    if (timerRef.current !== null) {
      window.clearInterval(timerRef.current);
      timerRef.current = null;
    }
    stopWaveformLoop();
    flushPlayback();

    if (callEventsRef.current) {
      callEventsRef.current.close();
      callEventsRef.current = null;
    }

    if (wsRef.current) {
      const ws = wsRef.current;
      ws.onopen = null;
      ws.onmessage = null;
      ws.onerror = null;
      ws.onclose = null;
      if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) {
        try {
          ws.close(1000, 'Client ended call');
        } catch {
          // Ignore close error
        }
      }
      wsRef.current = null;
    }

    workletNodeRef.current?.disconnect();
    workletNodeRef.current = null;
    micAnalyserRef.current?.disconnect();
    micAnalyserRef.current = null;
    sourceNodeRef.current?.disconnect();
    sourceNodeRef.current = null;
    silentGainRef.current?.disconnect();
    silentGainRef.current = null;
    playbackAnalyserRef.current?.disconnect();
    playbackAnalyserRef.current = null;

    if (mediaStreamRef.current) {
      mediaStreamRef.current.getTracks().forEach((track) => track.stop());
      mediaStreamRef.current = null;
    }
    if (captureCtxRef.current) {
      void captureCtxRef.current.close();
      captureCtxRef.current = null;
    }
    if (playbackCtxRef.current) {
      void playbackCtxRef.current.close();
      playbackCtxRef.current = null;
    }

    setActiveSpeaker('none');
    setPipelineStage('idle');
    setPipelineDetail('Standby');
  }, [flushPlayback, stopWaveformLoop]);

  const playPcmChunk = useCallback((buffer: ArrayBuffer) => {
    const ctx = playbackCtxRef.current;
    const analyser = playbackAnalyserRef.current;
    if (!ctx || !analyser || buffer.byteLength < 2) return;
    if (ctx.state === 'suspended') {
      void ctx.resume();
    }

    const pcm16 = new Int16Array(buffer);
    const float32 = new Float32Array(pcm16.length);
    for (let i = 0; i < pcm16.length; i++) {
      float32[i] = pcm16[i] / 32768;
    }

    const audioBuffer = ctx.createBuffer(1, float32.length, SAMPLE_RATE);
    audioBuffer.copyToChannel(float32, 0);

    const source = ctx.createBufferSource();
    source.buffer = audioBuffer;
    source.connect(analyser);

    const now = ctx.currentTime;
    const startAt = Math.max(now + 0.015, nextPlayTimeRef.current);
    source.start(startAt);
    nextPlayTimeRef.current = startAt + audioBuffer.duration;

    activeSourcesRef.current.add(source);
    source.onended = () => {
      activeSourcesRef.current.delete(source);
    };
  }, []);

  const attachCallTelemetry = useCallback(
    (eventsPath: string, expectedCallId: string) => {
      const es = new EventSource(eventsPath);
      callEventsRef.current = es;

      es.onmessage = (ev: MessageEvent<string>) => {
        try {
          const envelope = JSON.parse(ev.data) as EventEnvelope;
          if (envelope.call_id && envelope.call_id !== expectedCallId) return;
          const { type, data } = envelope;
          const ts = envelope.timestamp ?? new Date().toISOString();

          if (type === 'call.transcript') {
            const role = data.role === 'caller' ? 'caller' : 'agent';
            const text = String(data.text ?? '').trim();
            if (!text) return;
            const latencyMs = typeof data.latency_ms === 'number' ? data.latency_ms : null;
            setTranscript((prev) => [
              ...prev,
              { id: `tr-${envelope.id}`, role, text, timestamp: ts, latencyMs },
            ]);
          } else if (type === 'call.tool') {
            const summary = String(data.summary ?? 'Processing…');
            setTranscript((prev) => [
              ...prev,
              { id: `tool-${envelope.id}`, role: 'tool', text: summary, timestamp: ts },
            ]);
          } else if (type === 'call.metrics') {
            setMetrics((prev) => ({
              llmTtftMs:
                typeof data.llm_ttft_ms === 'number' ? data.llm_ttft_ms : prev.llmTtftMs,
              avgLlmTtftMs:
                typeof data.avg_llm_ttft_ms === 'number'
                  ? data.avg_llm_ttft_ms
                  : prev.avgLlmTtftMs,
              toolExecMs:
                typeof data.tool_exec_ms === 'number' ? data.tool_exec_ms : prev.toolExecMs,
              lastTool:
                typeof data.last_tool === 'string' ? data.last_tool : prev.lastTool,
            }));
          } else if (type === 'call.booking_confirmed') {
            const appt = data.appointment as Appointment | undefined;
            if (!appt) return;
            setTranscript((prev) => [
              ...prev,
              {
                id: `book-${envelope.id}`,
                role: 'booking',
                text: `Booked ${appt.doctor_name}`,
                timestamp: ts,
                appointment: appt,
              },
            ]);
          } else if (type === 'call.booking_cancelled') {
            const appt = data.appointment as Appointment | undefined;
            if (!appt) return;
            setTranscript((prev) => [
              ...prev,
              {
                id: `cancel-${envelope.id}`,
                role: 'cancellation',
                text: `Cancelled ${appt.doctor_name}`,
                timestamp: ts,
                appointment: appt,
              },
            ]);
          } else if (type === 'call.phone_verified') {
            setVerifiedPhone(String(data.phone_display ?? data.phone ?? ''));
          } else if (type === 'call.stage') {
            const stage = String(data.stage ?? 'idle') as PipelineStage;
            setPipelineStage(stage);
            setPipelineDetail(String(data.detail ?? 'Active'));
          } else if (type === 'call.vad') {
            const speaker = data.speaker === 'user' ? 'user' : 'agent';
            const speaking = Boolean(data.speaking);
            setActiveSpeaker(speaking ? speaker : 'none');
          } else if (type === 'call.barge_in') {
            flushPlayback();
          } else if (type === 'call.lifecycle') {
            if (data.status === 'error' && data.error) {
              setError(String(data.error));
            }
          }
        } catch {
          // Ignore heartbeat
        }
      };
    },
    [flushPlayback]
  );

  const startCall = useCallback(async () => {
    const attemptId = ++attemptSeqRef.current;
    cleanupResources();
    setError(null);
    setMuted(false);
    setElapsedSeconds(0);
    setTranscript([]);
    setVerifiedPhone(null);
    setMetrics(INITIAL_METRICS);
    setCallId(null);
    setStatus('ringing');
    setPipelineStage('vad');
    setPipelineDetail('Dialing front desk…');
    callSounds.startRing();

    try {
      const provision = await clinicApi.createCallSession();
      if (attemptId !== attemptSeqRef.current) return;
      setCallId(provision.call_id);

      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
          channelCount: 1,
        },
      });
      if (attemptId !== attemptSeqRef.current) {
        stream.getTracks().forEach((t) => t.stop());
        return;
      }
      mediaStreamRef.current = stream;

      const captureCtx = new AudioContext();
      captureCtxRef.current = captureCtx;
      if (captureCtx.state === 'suspended') {
        await captureCtx.resume();
      }
      await captureCtx.audioWorklet.addModule('/pcm-processor.js');

      const playbackCtx = new AudioContext({ sampleRate: SAMPLE_RATE });
      playbackCtxRef.current = playbackCtx;
      if (playbackCtx.state === 'suspended') {
        await playbackCtx.resume();
      }
      const playbackAnalyser = playbackCtx.createAnalyser();
      playbackAnalyser.fftSize = 128;
      playbackAnalyser.smoothingTimeConstant = 0.72;
      playbackAnalyser.connect(playbackCtx.destination);
      playbackAnalyserRef.current = playbackAnalyser;
      nextPlayTimeRef.current = playbackCtx.currentTime;

      // Brief authentic ringback pulse BEFORE opening the voice WS so greeting audio never overlaps the ringtone
      await new Promise<void>((resolve) => {
        ringTimeoutRef.current = window.setTimeout(() => {
          ringTimeoutRef.current = null;
          resolve();
        }, 700);
      });
      if (attemptId !== attemptSeqRef.current) return;

      attachCallTelemetry(provision.events_path, provision.call_id);

      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const ws = new WebSocket(`${protocol}//${window.location.host}${provision.ws_path}`);
      ws.binaryType = 'arraybuffer';
      wsRef.current = ws;

      ws.onopen = () => {
        if (attemptId !== attemptSeqRef.current || ws.readyState !== WebSocket.OPEN) return;

        callSounds.playConnected();
        setStatus('connected');
        setPipelineStage('idle');
        setPipelineDetail('Listening');

        const sourceNode = captureCtx.createMediaStreamSource(stream);
        const micAnalyser = captureCtx.createAnalyser();
        micAnalyser.fftSize = 128;
        micAnalyser.smoothingTimeConstant = 0.72;

        const workletNode = new AudioWorkletNode(captureCtx, 'pcm-capture-processor');
        const silentGain = captureCtx.createGain();
        silentGain.gain.value = 0;

        sourceNodeRef.current = sourceNode;
        micAnalyserRef.current = micAnalyser;
        workletNodeRef.current = workletNode;
        silentGainRef.current = silentGain;

        workletNode.port.onmessage = (
          event: MessageEvent<{ pcm: ArrayBuffer; rms: number }>
        ) => {
          if (mutedRef.current) return;
          if (
            ws.readyState === WebSocket.OPEN &&
            ws.bufferedAmount < MAX_WS_BUFFERED_BYTES
          ) {
            ws.send(event.data.pcm);
          }
        };

        sourceNode.connect(micAnalyser);
        micAnalyser.connect(workletNode);
        workletNode.connect(silentGain);
        silentGain.connect(captureCtx.destination);

        startWaveformLoop();

        const startedAt = Date.now();
        timerRef.current = window.setInterval(() => {
          setElapsedSeconds(Math.floor((Date.now() - startedAt) / 1000));
        }, 1000);
      };

      ws.onmessage = (event: MessageEvent) => {
        if (event.data instanceof ArrayBuffer) {
          playPcmChunk(event.data);
        }
      };

      ws.onerror = () => {
        setError('Unable to reach the voice server. Verify the Python backend is running.');
        cleanupResources();
        setStatus('ended');
      };

      ws.onclose = (ev: CloseEvent) => {
        if (ev.reason && ev.code !== 1000) {
          setError(ev.reason);
        }
        callSounds.playEnded();
        cleanupResources();
        setStatus('ended');
      };
    } catch (err) {
      if (attemptId !== attemptSeqRef.current) return;
      const msg =
        err instanceof Error
          ? err.message
          : 'Microphone access and backend connectivity are required to start a call.';
      setError(msg);
      cleanupResources();
      setStatus('ended');
    }
  }, [attachCallTelemetry, cleanupResources, playPcmChunk, startWaveformLoop]);

  const endCall = useCallback(() => {
    attemptSeqRef.current += 1;
    callSounds.playEnded();
    cleanupResources();
    setStatus('ended');
  }, [cleanupResources]);

  const toggleMute = useCallback(() => {
    setMuted((prev) => !prev);
  }, []);

  useEffect(() => {
    return () => {
      attemptSeqRef.current += 1;
      cleanupResources();
    };
  }, [cleanupResources]);

  return {
    callId,
    status,
    muted,
    elapsedSeconds,
    activeSpeaker,
    pipelineStage,
    pipelineDetail,
    verifiedPhone,
    metrics,
    waveform,
    transcript,
    error,
    startCall,
    endCall,
    toggleMute,
  };
}
