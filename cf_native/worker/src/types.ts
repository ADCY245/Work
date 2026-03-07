export interface Env {
  ENVIRONMENT: string;

  DB: D1Database;
  OTP_KV: KVNamespace;
  SESSION_KV: KVNamespace;

  META_WHATSAPP_TOKEN?: string;
  META_WHATSAPP_PHONE_NUMBER_ID?: string;
  META_WHATSAPP_API_VERSION?: string;

  SESSION_COOKIE_NAME?: string;
  SECRET_KEY?: string;
}
