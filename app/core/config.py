from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "PhysiHome"
    environment: Literal["dev", "prod", "test"] = "dev"

    # MongoDB
    mongodb_uri: str = Field("mongodb://localhost:27017", alias="MONGODB_URI")
    mongodb_db_name: str = Field("physihome", alias="MONGODB_DB_NAME")

    # Security / JWT
    secret_key: str = Field("CHANGE_ME", alias="SECRET_KEY")
    jwt_secret: str | None = Field(default=None, alias="JWT_SECRET")
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24
    session_cookie_name: str = "physihome_session"

    # OTP
    otp_length: int = 6
    otp_expiry_minutes: int = 10

    # OAuth (Google)
    google_client_id: str | None = Field(default=None, alias="GOOGLE_CLIENT_ID")
    google_client_secret: str | None = Field(default=None, alias="GOOGLE_CLIENT_SECRET")
    oauth_redirect_uri: str | None = Field(default=None, alias="GOOGLE_REDIRECT_URI")

    # Email (SMTP)
    smtp_host: str | None = Field(default=None, alias="SMTP_HOST")
    smtp_port: int | None = Field(default=None, alias="SMTP_PORT")
    smtp_username: str | None = Field(default=None, alias="SMTP_USERNAME")
    smtp_password: str | None = Field(default=None, alias="SMTP_PASSWORD")
    smtp_use_tls: bool = Field(default=True, alias="SMTP_USE_TLS")
    notifications_from_email: str | None = Field(
        default=None, alias="NOTIFY_FROM_EMAIL"
    )
    email_from_fallback: str | None = Field(default=None, alias="EMAIL_FROM")
    resend_api_key: str | None = Field(default=None, alias="RESEND_API_KEY")

    meta_whatsapp_token: str | None = Field(default=None, alias="META_WHATSAPP_TOKEN")
    meta_whatsapp_phone_number_id: str | None = Field(default=None, alias="META_WHATSAPP_PHONE_NUMBER_ID")
    meta_whatsapp_api_version: str | None = Field(default="v19.0", alias="META_WHATSAPP_API_VERSION")

    twilio_account_sid: str | None = Field(default=None, alias="TWILIO_ACCOUNT_SID")
    twilio_auth_token: str | None = Field(default=None, alias="TWILIO_AUTH_TOKEN")
    twilio_whatsapp_from: str | None = Field(default=None, alias="TWILIO_WHATSAPP_FROM")

    whatsapp_provider: str = Field(default="twilio", alias="WHATSAPP_PROVIDER")
    wa_web_service_url: str | None = Field(default=None, alias="WA_WEB_SERVICE_URL")
    wa_web_service_auth_token: str | None = Field(default=None, alias="WA_WEB_SERVICE_AUTH_TOKEN")

    admin_emails: list[str] = Field(
        default_factory=list,
        alias="ADMIN_EMAILS",
    )

    wa_message_notify_debounce_seconds: int = Field(
        default=600,
        alias="WA_MESSAGE_NOTIFY_DEBOUNCE_SECONDS",
    )
    message_presence_window_seconds: int = Field(
        default=20,
        alias="MESSAGE_PRESENCE_WINDOW_SECONDS",
    )
    video_call_api_url: str = Field(
        default="",
        alias="VIDEO_CALL_API_URL",
    )

    @model_validator(mode="after")
    def _ensure_notification_email(self):
        if not self.notifications_from_email:
            self.notifications_from_email = self.email_from_fallback
        return self

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        populate_by_name = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
