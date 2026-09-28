const STORAGE_KEY = "afterhours.deskId";
const CODE_KEY = "afterhours.demoCode";

export function getDeskId(): string {
  const existing = localStorage.getItem(STORAGE_KEY);
  if (existing) return existing;
  const id = crypto.randomUUID();
  localStorage.setItem(STORAGE_KEY, id);
  return id;
}

export function captureDemoCodeFromUrl(): void {
  const code = new URLSearchParams(window.location.search).get("code");
  if (code?.trim()) sessionStorage.setItem(CODE_KEY, code.trim());
}

export function hasDemoCode(): boolean {
  return Boolean(sessionStorage.getItem(CODE_KEY));
}

export function saveDemoCode(code: string): void {
  sessionStorage.setItem(CODE_KEY, code.trim());
}

export function clearDemoCode(): void {
  sessionStorage.removeItem(CODE_KEY);
}

export function deskHeaders(extra?: HeadersInit): Headers {
  const headers = new Headers(extra);
  headers.set("X-Desk-Id", getDeskId());
  const code = sessionStorage.getItem(CODE_KEY);
  if (code) headers.set("X-Demo-Code", code);
  return headers;
}
