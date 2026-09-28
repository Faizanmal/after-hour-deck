export type CallStatus = "idle" | "connecting" | "live" | "ending" | "error";

export type TranscriptLine = {
  id: string;
  role: "user" | "agent" | "system";
  text: string;
  partial?: boolean;
};

export type Appointment = {
  appointment_id: string;
  status: string;
  patient: string;
  when: string;
  start_at: string;
  provider: string;
  visit_type: string;
  phone: string;
};

export type BoardPayload = {
  open_slots: number;
  timezone: string;
  providers: { name: string; specialty: string }[];
  visit_types: { slug: string; name: string; duration_minutes: number }[];
  appointments: Appointment[];
};

export type SessionPayload = {
  token: string;
  expires_in_seconds: number;
  max_session_duration_seconds: number;
  ws_url: string;
  session: Record<string, unknown>;
};
