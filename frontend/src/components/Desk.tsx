"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { apiUrl } from "@/lib/api";
import {
  captureDemoCodeFromUrl,
  deskHeaders,
  hasDemoCode,
  saveDemoCode,
} from "@/lib/desk";
import { DemoAccessError, VoiceSession, type AgentEvent } from "@/lib/voice-agent";
import type { BoardPayload, CallStatus, TranscriptLine } from "@/lib/types";

function newId() {
  return crypto.randomUUID();
}

export default function Desk() {
  const [status, setStatus] = useState<CallStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const [lines, setLines] = useState<TranscriptLine[]>([]);
  const [board, setBoard] = useState<BoardPayload | null>(null);
  const [health, setHealth] = useState<{
    database?: string;
    clinic?: string;
    access_code_required?: boolean;
  } | null>(null);
  const [codeReady, setCodeReady] = useState(false);
  const [accessCode, setAccessCode] = useState("");
  const sessionRef = useRef<VoiceSession | null>(null);
  const userPartialRef = useRef<string | null>(null);

  const refreshBoard = useCallback(async () => {
    const res = await fetch(apiUrl("/api/appointments"), { headers: deskHeaders() });
    if (!res.ok) return;
    setBoard(await res.json());
  }, []);

  useEffect(() => {
    let cancelled = false;
    captureDemoCodeFromUrl();
    setCodeReady(hasDemoCode());

    void fetch(apiUrl("/api/health"))
      .then((r) => r.json())
      .then((data) => {
        if (!cancelled) setHealth(data);
      })
      .catch(() => {
        if (!cancelled) setHealth(null);
      });

    const loadBoard = () => {
      void fetch(apiUrl("/api/appointments"), { headers: deskHeaders() })
        .then((r) => (r.ok ? r.json() : null))
        .then((data) => {
          if (!cancelled && data) setBoard(data);
        })
        .catch(() => undefined);
    };

    loadBoard();
    const timer = setInterval(loadBoard, 2500);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [codeReady]);

  const onEvent = useCallback(
    (event: AgentEvent) => {
      if (event.type === "status") {
        setStatus(event.status);
        if (event.status === "error") setError(event.detail || "Call failed");
        return;
      }
      if (event.type === "ended") {
        setStatus("idle");
        sessionRef.current = null;
        return;
      }
      if (event.type === "user") {
        setLines((prev) => {
          const next = [...prev];
          if (event.partial) {
            if (userPartialRef.current) {
              const idx = next.findIndex((l) => l.id === userPartialRef.current);
              if (idx >= 0) next[idx] = { ...next[idx], text: event.text, partial: true };
              return next;
            }
            const id = newId();
            userPartialRef.current = id;
            next.push({ id, role: "user", text: event.text, partial: true });
            return next;
          }
          if (userPartialRef.current) {
            const idx = next.findIndex((l) => l.id === userPartialRef.current);
            if (idx >= 0) next[idx] = { ...next[idx], text: event.text, partial: false };
            userPartialRef.current = null;
            return next;
          }
          next.push({ id: newId(), role: "user", text: event.text });
          return next;
        });
        return;
      }
      if (event.type === "agent") {
        setLines((prev) => [...prev, { id: newId(), role: "agent", text: event.text }]);
        return;
      }
      if (event.type === "tool") {
        setLines((prev) => [
          ...prev,
          { id: newId(), role: "system", text: `Tool ${event.name}` },
        ]);
        void refreshBoard();
      }
    },
    [refreshBoard],
  );

  const startCall = async () => {
    setError(null);
    setLines([]);
    userPartialRef.current = null;
    const session = new VoiceSession(onEvent);
    sessionRef.current = session;
    try {
      await session.start();
    } catch (err) {
      if (err instanceof DemoAccessError) setCodeReady(false);
      setStatus("error");
      setError(err instanceof Error ? err.message : "Could not start call");
      sessionRef.current = null;
    }
  };

  const endCall = async () => {
    await sessionRef.current?.stop();
  };

  useEffect(() => {
    const onHide = () => {
      void sessionRef.current?.stop();
    };
    window.addEventListener("pagehide", onHide);
    return () => window.removeEventListener("pagehide", onHide);
  }, []);

  const live = status === "live";
  const needsCode = Boolean(health?.access_code_required) && !codeReady;
  const hint = useMemo(() => {
    if (needsCode) return "Enter the access code from the presentation link.";
    if (status === "connecting") return "Minting a one-time token and opening the agent…";
    if (status === "live") return "Speak naturally. Interrupt anytime. End the call when you’re done.";
    if (status === "ending") return "Ending the session cleanly so it doesn’t keep billing.";
    return "Try: “I need a cleaning Thursday afternoon.” Then confirm the time out loud.";
  }, [needsCode, status]);

  return (
    <div className="min-h-screen bg-[radial-gradient(1200px_circle_at_10%_-10%,#d7efe8_0%,transparent_45%),radial-gradient(900px_circle_at_100%_0%,#f3d9a4_0%,transparent_35%),#efe6d4]">
      <header className="border-b border-pine/10 px-6 py-5 md:px-10">
        <div className="mx-auto flex max-w-6xl flex-wrap items-end justify-between gap-4">
          <div>
            <p className="text-xs font-medium uppercase tracking-[0.22em] text-moss">
              After-Hours Desk
            </p>
            <h1 className="display mt-1 text-3xl italic text-pine-deep md:text-4xl">
              Riverside Family Dental
            </h1>
          </div>
          <div className="flex items-center gap-3 text-sm text-pine/80">
            <span className="rounded-full border border-pine/15 bg-white/70 px-3 py-1">
              DB: {health?.database ?? "…"}
            </span>
            <span
              className={`rounded-full px-3 py-1 ${
                live ? "bg-live text-white" : "border border-pine/15 bg-white/70"
              }`}
            >
              {live ? "On the line" : status === "connecting" ? "Connecting" : "Night line idle"}
            </span>
          </div>
        </div>
      </header>

      <main className="mx-auto grid max-w-6xl gap-6 px-6 py-8 md:grid-cols-[1.05fr_0.95fr] md:px-10">
        <section className="rounded-3xl border border-pine/10 bg-white/80 p-6 shadow-[0_20px_70px_-40px_rgba(19,64,60,0.7)] backdrop-blur">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h2 className="display text-2xl text-pine-deep">Night line</h2>
              <p className="mt-2 max-w-md text-sm leading-6 text-pine/70">{hint}</p>
            </div>
            {live ? (
              <button
                onClick={() => void endCall()}
                className="rounded-full bg-live px-5 py-2.5 text-sm font-medium text-white"
              >
                End call
              </button>
            ) : (
              <button
                onClick={() => void startCall()}
                disabled={needsCode || status === "connecting" || status === "ending"}
                className="rounded-full bg-pine px-5 py-2.5 text-sm font-medium text-paper disabled:opacity-60"
              >
                {status === "connecting" ? "Connecting…" : "Start call"}
              </button>
            )}
          </div>

          {needsCode ? (
            <form
              className="mt-4 flex flex-wrap gap-2"
              onSubmit={(event) => {
                event.preventDefault();
                const next = accessCode.trim();
                if (!next) return;
                saveDemoCode(next);
                setAccessCode("");
                setError(null);
                setCodeReady(true);
              }}
            >
              <input
                value={accessCode}
                onChange={(event) => setAccessCode(event.target.value)}
                placeholder="Access code"
                autoComplete="off"
                className="min-w-40 flex-1 rounded-full border border-pine/15 bg-white px-4 py-2 text-sm text-pine-deep"
              />
              <button
                type="submit"
                className="rounded-full bg-pine px-5 py-2.5 text-sm font-medium text-paper"
              >
                Unlock
              </button>
            </form>
          ) : null}

          {error ? (
            <p className="mt-4 rounded-2xl bg-live/10 px-4 py-3 text-sm text-live">{error}</p>
          ) : null}

          <div className="mt-6 h-[28rem] overflow-y-auto rounded-2xl bg-pine-deep p-4 text-paper">
            {lines.length === 0 ? (
              <p className="pt-24 text-center text-sm text-paper/50">
                The transcript appears here. Allow the microphone when the browser asks.
              </p>
            ) : (
              <ul className="space-y-3">
                {lines.map((line) => (
                  <li key={line.id} className="text-sm leading-6">
                    <span className="mr-2 text-[11px] uppercase tracking-wider text-gold">
                      {line.role === "user" ? "Caller" : line.role === "agent" ? "Desk" : "System"}
                    </span>
                    <span className={line.partial ? "text-paper/60 italic" : ""}>{line.text}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </section>

        <section className="rounded-3xl border border-pine/10 bg-pine text-paper p-6">
          <div className="flex items-baseline justify-between">
            <h2 className="display text-2xl italic">Board</h2>
            <p className="text-xs uppercase tracking-widest text-gold">
              {board?.open_slots ?? "—"} open slots
            </p>
          </div>
          <p className="mt-1 text-sm text-paper/70">
            This browser keeps its own board, so other testers can book at the same time.
          </p>

          <div className="mt-5 grid grid-cols-2 gap-2 text-xs">
            {(board?.providers ?? []).map((p) => (
              <div key={p.name} className="rounded-2xl bg-white/10 px-3 py-2">
                <div className="font-medium">{p.name}</div>
                <div className="text-paper/60">{p.specialty}</div>
              </div>
            ))}
          </div>

          <ul className="mt-5 space-y-3">
            {(board?.appointments ?? []).length === 0 ? (
              <li className="rounded-2xl bg-white/10 px-4 py-8 text-center text-sm text-paper/60">
                No visits on the board yet.
              </li>
            ) : (
              board?.appointments.map((appt) => (
                <li
                  key={appt.appointment_id}
                  className="rounded-2xl bg-white/10 px-4 py-3"
                >
                  <div className="flex items-center justify-between gap-3">
                    <p className="font-medium">{appt.patient}</p>
                    <span
                      className={`rounded-full px-2 py-0.5 text-[10px] uppercase tracking-wide ${
                        appt.status === "cancelled" ? "bg-live/30" : "bg-gold/20 text-gold"
                      }`}
                    >
                      {appt.status}
                    </span>
                  </div>
                  <p className="mt-1 text-sm text-paper/75">{appt.when}</p>
                  <p className="text-xs text-paper/55">
                    {appt.visit_type} · {appt.provider} · {appt.appointment_id}
                  </p>
                </li>
              ))
            )}
          </ul>
        </section>
      </main>
    </div>
  );
}
