# After-Hours Desk

A clinic front-desk voice agent for the [AssemblyAI Voice Agent Hackathon](https://lablab.ai/ai-hackathons/assemblyai-voice-agent-hackathon).

Talk to **Riverside Family Dental** after hours. The agent books, moves, and cancels visits against a real clinic board — PostgreSQL when it is running, SQLite if it is not.

## Stack

- **Voice:** [AssemblyAI Voice Agent API](https://www.assemblyai.com/docs/voice-agents/voice-agent-api) (`alba`, 24 kHz PCM, function tools)
- **Frontend:** Next.js App Router, TypeScript, Tailwind
- **Backend:** Python FastAPI
- **Data:** PostgreSQL primary, SQLite fallback

The browser never sees your API key. Python mints a single-use token. End call sends `session.end` so the session does not keep billing.

## Setup

1. Create an API key at [assemblyai.com/dashboard/api-keys](https://www.assemblyai.com/dashboard/api-keys).

2. Backend env:

```powershell
cd backend
copy .env.example .env
```

Put the key in `ASSEMBLYAI_API_KEY`.

3. Optional PostgreSQL:

```powershell
docker compose up -d
```

If Postgres is down, the API logs a warning and uses `backend/clinic.db`.

4. Install and run (two terminals):

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\uvicorn app.main:app --reload --port 8000
```

```powershell
cd frontend
npm install
npm run dev
```

Open [http://localhost:3005](http://localhost:3005). The frontend uses port **3005** so it does not collide with other local apps on 3000.

## Demo script (~90 seconds)

Seeded patient: **Maya Hernandez**, born **April 12, 1988**.

1. Click **Start call** and allow the microphone.
2. Say: “I need a cleaning Thursday afternoon.”
3. Confirm the name, day, and time out loud when asked.
4. Watch the board on the right update.
5. Say: “Cancel Maya’s visit.”
6. Click **End call**.

## Tools

| Tool | What it does |
| --- | --- |
| `lookup_patient` | Name + date of birth |
| `list_available_slots` | Real open slots only — the agent must not invent times |
| `book_appointment` | Refuses unless `caller_confirmed` is true |
| `cancel_appointment` | Frees the slot |
| `get_prep_instructions` | Cleaning / consult / emergency prep |

Medical Mode (`domain: medical-v1`) is not a Voice Agent setting. Domain terms are boosted with `transcription_prompt` and `keyterms`.
