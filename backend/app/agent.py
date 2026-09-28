from __future__ import annotations

import logging
from datetime import datetime

import httpx

from app.config import Settings, get_settings
from app.seed import clinic_zone
from app.tools import TOOL_DEFINITIONS

AGENT_NAME = "After-Hours Desk"
logger = logging.getLogger(__name__)


def _auth_headers(settings: Settings) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.assemblyai_api_key}",
        "Content-Type": "application/json",
    }


def build_system_prompt(clinic_name: str) -> str:
    now = datetime.now(clinic_zone())
    spoken_now = now.strftime("%A, %B ") + str(now.day) + now.strftime(", %Y") + now.strftime(" %I:%M %p")
    return f"""BE SHORT. This is the most important rule. Keep every response under two sentences.

You are the after-hours front desk at {clinic_name}, on a live phone call. You book, reschedule, cancel, and give prep instructions. You are not a clinician.

Current local date and time: {spoken_now} ({now.tzname()}). Use this when the caller says today, tomorrow, Thursday, or afternoon.

Never book until the caller confirms name, date, and time out loud. Then call book_appointment with caller_confirmed true. If they have not confirmed, caller_confirmed stays false.

Never invent appointment times. Call list_available_slots and only offer slot times it returns. Read at most three options.

Things you CAN do:
- Look up a patient with lookup_patient
- Offer real open slots with list_available_slots
- Book after confirmation with book_appointment
- Cancel with cancel_appointment
- Share prep steps with get_prep_instructions

Things you CANNOT do:
- Diagnose, prescribe, or guess clinical advice
- Take insurance details or payment
- Promise a human callback tonight
- Collect Social Security numbers or full card numbers

Pinned facts:
- Clinic: {clinic_name}
- Providers: Dr. Amina Patel (hygiene / cleanings) and Dr. Wei Chen (general / consults)
- Visit types: cleaning, consult, emergency
- Hours on the board: weekdays 9 to 4, closed 12 to 1
- Demo patients on file: Maya Hernandez born April 12, 1988; James Okonkwo born November 3, 1975; Priya Shah born July 21, 1992

Never say "certainly", "absolutely", "happy to help", "great question", or "I'd be happy to help with that".
No markdown, bullets, or asterisks. TTS would read them aloud.
Say dates like "Thursday the 17th at 2 in the afternoon", not ISO strings.
If a tool returns error, say the useful part and ask only for the missing field.

Match the caller's length. If they are in pain, be brief and offer emergency slots first.
"""


def build_greeting(clinic_name: str) -> str:
    return f"Riverside after hours, this is the front desk at {clinic_name}. Are you calling to book, move, or cancel a visit?"


def build_session_config() -> dict:
    settings = get_settings()
    clinic_name = settings.clinic_name
    return {
        "system_prompt": build_system_prompt(clinic_name),
        "greeting": build_greeting(clinic_name),
        "tools": TOOL_DEFINITIONS,
        "input": {
            "format": {"encoding": "audio/pcm", "sample_rate": 24000},
            "transcription_mode": "balanced",
            "transcription_prompt": (
                "After-hours dental clinic front desk. Expect patient names, dates of birth, "
                "visit types cleaning consult emergency, and providers Dr. Patel and Dr. Chen."
            ),
            "keyterms": [
                "Riverside Family Dental",
                "Patel",
                "Chen",
                "Amina",
                "Wei",
                "Maya Hernandez",
                "James Okonkwo",
                "Priya Shah",
                "cleaning",
                "consult",
                "emergency",
                "reschedule",
                "fluoride",
            ],
            "voice_focus": "near-field",
            "voice_focus_threshold": 0.85,
            "turn_detection": {
                "vad_threshold": 0.5,
                "min_silence": 800,
                "max_silence": 1800,
                "interrupt_response": True,
                "interruption_delay": 100,
            },
        },
        "output": {
            "voice": settings.agent_voice,
            "format": {"encoding": "audio/pcm", "sample_rate": 24000},
            "volume": 100,
        },
    }


async def mint_voice_token() -> dict:
    settings = get_settings()
    if not settings.assemblyai_api_key or settings.assemblyai_api_key.startswith("your_"):
        raise RuntimeError("ASSEMBLYAI_API_KEY is missing. Copy backend/.env.example to backend/.env.")

    params = {
        "expires_in_seconds": str(settings.token_expires_in_seconds),
        "max_session_duration_seconds": str(settings.max_session_duration_seconds),
    }
    url = f"{settings.agents_api_base}/v1/token"
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(url, headers=_auth_headers(settings), params=params)
        if response.status_code >= 400:
            logger.warning("Token mint failed (%s): %s", response.status_code, response.text[:500])
            if response.status_code == 429:
                raise RuntimeError("The voice service is busy. Wait a minute and try again.")
            raise RuntimeError("The voice service could not start a call. Try again in a minute.")
        data = response.json()
    return {
        "token": data["token"],
        "expires_in_seconds": data.get("expires_in_seconds", settings.token_expires_in_seconds),
        "max_session_duration_seconds": settings.max_session_duration_seconds,
        "ws_url": "wss://agents.assemblyai.com/v1/ws",
        "session": build_session_config(),
    }
