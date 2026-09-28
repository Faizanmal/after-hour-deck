import { apiUrl } from "./api";
import { clearDemoCode, deskHeaders } from "./desk";
import type { SessionPayload } from "./types";

export type AgentEvent =
  | { type: "status"; status: "connecting" | "live" | "ending" | "idle" | "error"; detail?: string }
  | { type: "user"; text: string; partial: boolean }
  | { type: "agent"; text: string; partial: boolean }
  | { type: "tool"; name: string; result: unknown }
  | { type: "ended" };

type PendingTool = { call_id: string; result: unknown };

export class DemoAccessError extends Error {}

function pcmToBase64(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunk));
  }
  return btoa(binary);
}

function decodePcm16(b64: string): Float32Array {
  const raw = atob(b64);
  const pcm16 = new Int16Array(raw.length / 2);
  for (let i = 0; i < pcm16.length; i++) {
    pcm16[i] = raw.charCodeAt(i * 2) | (raw.charCodeAt(i * 2 + 1) << 8);
  }
  const float32 = new Float32Array(pcm16.length);
  for (let i = 0; i < pcm16.length; i++) {
    float32[i] = pcm16[i] / 32768;
  }
  return float32;
}

export class VoiceSession {
  private ws: WebSocket | null = null;
  private stream: MediaStream | null = null;
  private audioCtx: AudioContext | null = null;
  private worklet: AudioWorkletNode | null = null;
  private source: MediaStreamAudioSourceNode | null = null;
  private ready = false;
  private lastEvent: string | null = null;
  private pending: PendingTool[] = [];
  private playbackTime = 0;
  private sources: AudioBufferSourceNode[] = [];
  private onEvent: (event: AgentEvent) => void;
  private ended = false;

  constructor(onEvent: (event: AgentEvent) => void) {
    this.onEvent = onEvent;
  }

  async start() {
    this.ended = false;
    this.onEvent({ type: "status", status: "connecting" });
    try {
      this.audioCtx = new AudioContext();
      await this.audioCtx.resume();
      await this.audioCtx.audioWorklet.addModule("/pcm-processor.js");

      const sessionRes = await fetch(apiUrl("/api/session"), { headers: deskHeaders() });
      if (!sessionRes.ok) {
        const body = await sessionRes.json().catch(() => ({ detail: sessionRes.statusText }));
        const detail = body.detail || "Could not mint a voice session token";
        if (sessionRes.status === 401) {
          clearDemoCode();
          throw new DemoAccessError(detail);
        }
        throw new Error(detail);
      }
      const payload = (await sessionRes.json()) as SessionPayload;

      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: false,
          channelCount: 1,
        },
      });

      const audioTracks = this.stream.getAudioTracks();
      if (audioTracks.length === 0 || audioTracks.every((track) => track.readyState !== "live")) {
        throw new Error("No live microphone track is available. Check browser and Windows microphone permissions.");
      }

      if (!this.audioCtx) {
        throw new Error("Audio context failed to start");
      }

      this.worklet = new AudioWorkletNode(this.audioCtx, "pcm-processor", {
        processorOptions: {
          inputSampleRate: this.audioCtx.sampleRate,
          targetSampleRate: 24000,
        },
      });
      this.source = this.audioCtx.createMediaStreamSource(this.stream);
      this.source.connect(this.worklet);

      const wsUrl = new URL(payload.ws_url);
      wsUrl.searchParams.set("token", payload.token);
      this.ws = new WebSocket(wsUrl);

      this.worklet.port.onmessage = (event) => {
        if (!this.ready || !this.ws || this.ws.readyState !== WebSocket.OPEN) return;
        this.ws.send(
          JSON.stringify({
            type: "input.audio",
            audio: pcmToBase64(event.data as ArrayBuffer),
          }),
        );
      };

      this.ws.addEventListener("open", () => {
        this.ws?.send(
          JSON.stringify({
            type: "session.update",
            session: payload.session,
          }),
        );
      });

      this.ws.addEventListener("message", (event) => {
        void this.handleMessage(JSON.parse(event.data as string));
      });

      this.ws.addEventListener("close", () => {
        if (!this.ended) {
          this.onEvent({ type: "status", status: "error", detail: "Socket closed" });
        }
        this.cleanup();
      });

      this.ws.addEventListener("error", () => {
        this.onEvent({ type: "status", status: "error", detail: "WebSocket error" });
      });
    } catch (err) {
      this.cleanup();
      if (err instanceof DOMException && err.name === "NotAllowedError") {
        throw new Error("Microphone access was blocked. Allow microphone access for localhost and try again.");
      }
      if (err instanceof DOMException && err.name === "NotFoundError") {
        throw new Error("No microphone was found. Connect or enable a microphone and try again.");
      }
      if (err instanceof DOMException && err.message.toLowerCase().includes("audio source")) {
        throw new Error("The microphone is unavailable or already in use. Close other audio apps, then try again.");
      }
      throw err;
    }
  }

  async stop() {
    this.ended = true;
    this.onEvent({ type: "status", status: "ending" });
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: "session.end" }));
      return;
    }
    this.cleanup();
    this.onEvent({ type: "ended" });
  }

  private async handleMessage(msg: Record<string, unknown>) {
    const type = String(msg.type || "");

    if (type === "session.ready") {
      this.ready = true;
      this.playbackTime = this.audioCtx?.currentTime ?? 0;
      this.onEvent({ type: "status", status: "live" });
      return;
    }

    if (type === "session.ended") {
      this.ended = true;
      this.cleanup();
      this.onEvent({ type: "ended" });
      return;
    }

    if (type === "session.error" || type === "error") {
      this.onEvent({
        type: "status",
        status: "error",
        detail: String(msg.message || msg.error || "Session error"),
      });
      return;
    }

    if (type === "transcript.user.delta") {
      this.onEvent({ type: "user", text: String(msg.text || ""), partial: true });
      return;
    }
    if (type === "transcript.user") {
      this.lastEvent = type;
      this.onEvent({ type: "user", text: String(msg.text || ""), partial: false });
      return;
    }
    if (type === "transcript.agent") {
      this.onEvent({ type: "agent", text: String(msg.text || ""), partial: false });
      return;
    }

    if (type === "reply.started" || type === "input.speech.started") {
      this.lastEvent = type;
      return;
    }

    if (type === "reply.audio") {
      this.playChunk(String(msg.data || ""));
      return;
    }

    if (type === "reply.done") {
      this.lastEvent = type;
      if (msg.status === "interrupted") {
        this.flushPlayback();
        this.pending = [];
        return;
      }
      await this.flushTools();
      return;
    }

    if (type === "tool.call") {
      const callId = String(msg.call_id || "");
      const name = String(msg.name || "");
      let args = msg.arguments as unknown;
      if (typeof args === "string") {
        try {
          args = JSON.parse(args);
        } catch {
          args = {};
        }
      }
      try {
        const res = await fetch(apiUrl("/api/tools/execute"), {
          method: "POST",
          headers: deskHeaders({ "Content-Type": "application/json" }),
          body: JSON.stringify({ name, arguments: args || {}, call_id: callId }),
        });
        const body = await res.json();
        this.pending.push({ call_id: callId, result: body.result });
        this.onEvent({ type: "tool", name, result: body.result });
        await this.flushTools();
      } catch (err) {
        this.pending.push({
          call_id: callId,
          result: { error: err instanceof Error ? err.message : "Tool failed" },
        });
        await this.flushTools();
      }
    }
  }

  private async flushTools() {
    if (this.lastEvent !== "reply.done" || !this.pending.length) return;
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
    for (const tool of this.pending) {
      this.ws.send(
        JSON.stringify({
          type: "tool.result",
          call_id: tool.call_id,
          result: JSON.stringify(tool.result),
        }),
      );
    }
    this.pending = [];
  }

  private playChunk(b64: string) {
    if (!this.audioCtx || !b64) return;
    const float32 = decodePcm16(b64);
    const buffer = this.audioCtx.createBuffer(1, float32.length, 24000);
    buffer.getChannelData(0).set(float32);
    const src = this.audioCtx.createBufferSource();
    src.buffer = buffer;
    src.connect(this.audioCtx.destination);
    const now = this.audioCtx.currentTime;
    this.playbackTime = Math.max(this.playbackTime, now);
    src.start(this.playbackTime);
    this.playbackTime += buffer.duration;
    this.sources.push(src);
    src.onended = () => {
      this.sources = this.sources.filter((s) => s !== src);
    };
  }

  private flushPlayback() {
    for (const src of this.sources) {
      try {
        src.stop();
      } catch {
        /* already stopped */
      }
    }
    this.sources = [];
    this.playbackTime = this.audioCtx?.currentTime ?? 0;
  }

  private cleanup() {
    this.ready = false;
    this.worklet?.port.close();
    try {
      this.source?.disconnect();
      this.worklet?.disconnect();
    } catch {
      /* ignore */
    }
    this.stream?.getTracks().forEach((track) => track.stop());
    this.flushPlayback();
    void this.audioCtx?.close();
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.close();
    }
    this.ws = null;
    this.stream = null;
    this.audioCtx = null;
    this.worklet = null;
    this.source = null;
  }
}
