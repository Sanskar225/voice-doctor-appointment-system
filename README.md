# Aurelia Health — Voice AI Doctor Appointment Assistant

[![CI](https://github.com/Sanskar225/voice-doctor-appointment-system/actions/workflows/ci.yml/badge.svg)](https://github.com/Sanskar225/voice-doctor-appointment-system/actions/workflows/ci.yml)

Real-time voice AI doctor appointment receptionist built with **Pipecat**, **ElevenLabs (STT + TTS)**, **Google Gemini**, **Silero VAD**, and a live **React + TypeScript** clinical front-desk dashboard.

Callers speak directly from the browser to **Maya**, the clinic receptionist. Callers are identified strictly by the phone number they say out loud — no login, OTP, or caller ID. Maya reads the number back for explicit confirmation before booking or cancelling, and every slot/appointment change reflects live across the dashboard.

---

## Architecture Overview

```text
Browser Mic (AudioWorklet 16 kHz PCM)
   │  Binary WebSocket (/ws/voice/{call_id})
   ▼
FastAPIWebsocketTransport + RawPCMFrameSerializer
   ▼
ElevenLabs STT (Scribe v2 + physician keyterms)
   ▼
UserSpeechObserver ──► Call-Scoped SSE (/api/v1/events?call_id=...)
   ▼
LLMContextAggregatorPair + SileroVADAnalyzer (turn detection & barge-in)
   ▼
GoogleLLMService (Gemini 3.1 Flash Lite)
   ├── check_doctor_availability()  ──► AppointmentService ──► SQLite (WAL)
   ├── book_appointment()           ──► Atomic BEGIN IMMEDIATE + Clinic SSE delta
   └── cancel_appointment()         ──► Atomic slot reopen    + Clinic SSE delta
   ▼
AssistantSpeechObserver (clean barge-in flush)
   ▼
ElevenLabs TTS (eleven_flash_v2_5, 16 kHz PCM) ──► Browser Web Audio + FFT Visualizer
```

For deep-dive design rationale (latency tuning, concurrency invariants, SSE state versioning, and call isolation), see **[docs/architecture.md](docs/architecture.md)**.

---

## Repository Structure

```text
.
├── .env.example                 # Environment variable template (never commit .env)
├── docs/
│   └── architecture.md          # Detailed system design & trade-off documentation
├── backend/
│   ├── pyproject.toml           # Project metadata, pytest & ruff configuration
│   ├── requirements.txt         # Python dependencies
│   ├── app/
│   │   ├── main.py              # FastAPI app factory, lifespan, CORS, domain error handlers
│   │   ├── config.py            # Typed Settings loaded once at boot
│   │   ├── logging_config.py    # ContextVar call_id structured logging
│   │   ├── domain/              # Immutable Pydantic v2 DTOs & typed DomainError hierarchy
│   │   ├── infrastructure/      # SQLite WAL DatabaseManager, ClinicRepository, Scoped EventBus
│   │   ├── services/            # Async AppointmentService (off-loop SQLite, phone guardrails)
│   │   ├── voice/               # Pipecat pipeline, Silero VAD, Tools, Observers, CallSessionManager
│   │   └── api/                 # AppContainer DI + versioned /api/v1 & /ws/voice/{call_id} routes
│   └── tests/                   # Unit, concurrency, Pipecat voice & FastAPI integration tests
└── frontend/
    ├── public/pcm-processor.js  # AudioWorklet 16 kHz PCM downsampler
    └── src/
        ├── types/               # Strict TypeScript DTOs mirroring backend schemas
        ├── api/                 # Typed HTTP client (AbortSignal + ApiError)
        ├── state/               # Deterministic versioned clinicReducer (delta updates)
        ├── hooks/               # useClinicSync (clinic SSE) & useVoiceCall (call SSE + WebAudio FFT)
        ├── utils/               # Server-date formatting & synthesized Web Audio telephony tones
        └── components/          # Masthead, DoctorsPanel, AppointmentsPanel, CallLogsView, AgentView, PhoneCallSheet
```

### Designed for Both SDE & FDE Workflows
- **SDE Foundations**: Hexagonal ports (`ClinicRepositoryPort`, `EventPublisherPort`), explicit `AppContainer` DI, SQLite WAL with numbered `schema_migrations`, database-level partial unique index + state `CHECK` constraints, `PhoneReadbackTracker` state-machine policy, off-loop atomic transactions, deep `/api/v1/readiness` DB probe + security response headers, GitHub Actions CI, and 13 automated tests (`pytest -v`).
- **FDE Client Deployment & Observability**:
  - **Live Client Configuration (`Agent & Pipeline`)**: Customize clinic name, receptionist name, greeting tone (`Warm` / `Formal`), TTS speech cadence, and strict phone read-back policy via `PATCH /api/v1/config` — takes effect on the very next call with **zero restart**.
  - **Call Logs & Latency Telemetry (`Call Logs`)**: Durable SQLite `call_sessions` + `call_transcripts` recording every turn, tool execution duration (`ms`), and Gemini Time-to-First-Token (`TTFT ms`) alongside live pipeline stage illumination.

---

## Tech Stack
- **Voice Framework**: Python 3.12 + [Pipecat](https://github.com/pipecat-ai/pipecat) (`pipecat-ai>=1.0.0`)
- **VAD**: Silero VAD (`SileroVADAnalyzer`)
- **STT**: ElevenLabs Scribe v2 (`ElevenLabsRealtimeSTTService` with `ELEVENLABS_STT_MODE=segmented` fallback)
- **LLM**: **Google Gemini 3.1 Flash Lite** (`GoogleLLMService`, ultra-low latency free tier via Google AI Studio; supports opt-in Vertex AI Express Mode via `GEMINI_USE_VERTEX=true`)
- **TTS**: ElevenLabs Flash v2.5 (`ElevenLabsTTSService`, `eleven_flash_v2_5`, free-tier premade voice Sarah)
- **Database**: SQLite in WAL mode (`backend/clinic.db`, auto-seeded with 5 physicians across 5 specialties)
- **Frontend**: React 18, TypeScript, Vite, Web Audio API

---

## Quick Start

### 1. Configure API Keys
Copy `.env.example` to `.env` in the repository root and set:
- `ELEVENLABS_API_KEY`
- `GEMINI_API_KEY`

```bash
cp .env.example .env
```

### 2. Run the Backend

```bash
cd backend
py -3.12 -m venv .venv
# Windows PowerShell:
.\.venv\Scripts\Activate.ps1
# macOS / Linux:
# source .venv/bin/activate

pip install -r requirements.txt
pytest -v
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 3. Run the Frontend

```bash
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173**, click **Try Call**, grant microphone permission, and speak naturally.

### 4. Production Docker Run (Optional)

Run the full stack behind an Nginx reverse proxy (configured for unbuffered SSE and bidirectional 16 kHz PCM WebSockets) with persistent SQLite WAL storage:

```bash
cp .env.example .env   # add ELEVENLABS_API_KEY and GEMINI_API_KEY
docker compose up --build
```

- Dashboard + API/WS proxy: **http://localhost:5173**
- Backend liveness & deep DB readiness probes: `GET /api/v1/health` · `GET /api/v1/readiness`
