export interface Env {
  ENVIRONMENT: string;

  DB: D1Database;
  OTP_KV: KVNamespace;
  SESSION_KV: KVNamespace;

  RESEND_API_KEY?: string;

  SESSION_COOKIE_NAME?: string;
  SECRET_KEY?: string;
}
