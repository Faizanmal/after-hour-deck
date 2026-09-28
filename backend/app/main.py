from __future__ import annotations

import json
import logging
import re
import secrets
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import clinic
from app import database as dbmod
from app.agent import mint_voice_token
from app.config import get_settings
from app.database import get_db, init_db
from app.limits import client_ip, inflight, limiter
from app.models import Desk
from app.seed import ensure_desk, seed_if_empty
from app.tools import run_tool

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    if settings.public_demo and not settings.demo_access_code.strip():
        raise RuntimeError("PUBLIC_DEMO is on and DEMO_ACCESS_CODE is empty.")
    init_db()
    from app.database import SessionLocal

    assert SessionLocal is not None
    db = SessionLocal()
    try:
        seed_if_empty(db)
        db.commit()
    finally:
        db.close()
    logger.info("Database ready (%s)", dbmod.db_backend)
    yield


app = FastAPI(title="After-Hours Desk", lifespan=lifespan)

_MAX_BODY_BYTES = 32_768
_FLOOD_PER_IP = 1200
_FLOOD_GLOBAL = 2400


@app.middleware("http")
async def reject_floods(request: Request, call_next):
    if not request.url.path.startswith("/api"):
        return await call_next(request)
    if request.method in {"POST", "PUT", "PATCH"}:
        raw_length = request.headers.get("content-length")
        if raw_length is None or not raw_length.isdigit() or int(raw_length) > _MAX_BODY_BYTES:
            return JSONResponse(status_code=413, content={"detail": "Request is too large."})
    ip = client_ip(request)
    blocked = limiter.allow(
        [
            (f"flood:{ip}", _FLOOD_PER_IP, 60),
            ("flood-global", _FLOOD_GLOBAL, 60),
        ]
    )
    if blocked:
        return JSONResponse(
            status_code=429,
            content={"detail": "The desk is busy. Wait a moment and try again."},
            headers={"Retry-After": "1"},
        )
    held = inflight.enter(ip)
    if held:
        return JSONResponse(
            status_code=429,
            content={"detail": "The desk is busy. Wait a moment and try again."},
            headers={"Retry-After": "1"},
        )
    try:
        return await call_next(request)
    finally:
        inflight.leave(ip)


_settings = get_settings()
_cors_origins = [origin.strip() for origin in _settings.cors_origins.split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_origin_regex=r"https://.*\.vercel\.app" if _settings.public_demo else None,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ToolExecuteBody(BaseModel):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    call_id: str | None = None


DbSession = Annotated[Session, Depends(get_db)]
_DESK_ID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def _too_many(detail: str) -> HTTPException:
    return HTTPException(status_code=429, detail=detail, headers={"Retry-After": "60"})


def _limited(checks: list[tuple[str, int, int]]) -> str | None:
    if not get_settings().public_demo:
        return None
    return limiter.allow(checks)


def enforce_demo_code(request: Request, x_demo_code: str | None) -> None:
    settings = get_settings()
    if not settings.public_demo:
        return
    expected = settings.demo_access_code.strip()
    provided = (x_demo_code or "").strip()
    if not expected or not secrets.compare_digest(provided, expected):
        ip = client_ip(request)
        if _limited([("code", 30, 600), (f"code:{ip}", 20, 600)]):
            raise _too_many("Too many access attempts. Wait a few minutes and try again.")
        raise HTTPException(status_code=401, detail="Open the presentation link to start a call.")


def require_desk(
    request: Request,
    db: DbSession,
    x_desk_id: Annotated[str | None, Header()] = None,
    x_demo_code: Annotated[str | None, Header()] = None,
) -> Desk:
    enforce_demo_code(request, x_demo_code)
    if x_desk_id is None or not _DESK_ID.fullmatch(x_desk_id):
        raise HTTPException(status_code=400, detail="Open the desk in a browser so it can keep its own board.")
    ip = client_ip(request)
    existing = db.scalar(select(Desk.id).where(Desk.public_id == x_desk_id))
    if existing is None:
        blocked = _limited(
            [
                (f"desk:{ip}", 30, 3600),
                ("desk-global", 300, 3600),
            ]
        )
        if blocked:
            raise _too_many("Too many new boards were opened. Wait a while and try again.")
    return ensure_desk(db, x_desk_id)


DeskDep = Annotated[Desk, Depends(require_desk)]


@app.get("/api/health")
def health() -> dict[str, Any]:
    settings = get_settings()
    return {
        "status": "ok",
        "database": dbmod.db_backend,
        "clinic": settings.clinic_name,
        "voice": settings.agent_voice,
        "access_code_required": settings.public_demo,
    }


@app.get("/api/session")
async def session(
    request: Request,
    x_demo_code: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
    enforce_demo_code(request, x_demo_code)
    settings = get_settings()
    ip = client_ip(request)
    blocked = _limited(
        [
            (f"session:{ip}", settings.session_limit_per_ip, 3600),
            ("session-global", settings.session_limit_global, 3600),
        ]
    )
    if blocked == "session-global":
        raise _too_many("The demo has hit its hourly call limit. Try again shortly.")
    if blocked:
        raise _too_many("Too many calls were started from this network. Wait a bit and try again.")
    try:
        return await mint_voice_token()
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/tools/execute")
def execute_tool(body: ToolExecuteBody, request: Request, db: DbSession, desk: DeskDep) -> dict[str, Any]:
    arguments = body.arguments
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError:
            arguments = {}
    blocked = _limited(
        [
            (f"tool:{desk.public_id}", 40, 60),
            (f"tool-ip:{client_ip(request)}", 80, 60),
        ]
    )
    if blocked:
        raise _too_many("Too many booking requests. Wait a minute and try again.")
    result = run_tool(db, desk, body.name, arguments)
    return {"call_id": body.call_id, "name": body.name, "result": result}


@app.get("/api/appointments")
def appointments(db: DbSession, desk: DeskDep) -> dict[str, Any]:
    blocked = _limited([(f"board:{desk.public_id}", 40, 60)])
    if blocked:
        raise _too_many("The board is refreshing too quickly. Wait a minute.")
    return clinic.list_board(db, desk)
