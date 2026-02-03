from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "PhysiHome"
    environment: Literal["dev", "prod", "test"] = "dev"

    # MongoDB
    mongodb_uri: str = Field("mongodb://localhost:27017", alias="MONGODB_URI")
    mongodb_db_name: str = Field("physihome", alias="MONGODB_DB_NAME")

    # Security / JWT
    secret_key: str = Field("CHANGE_ME", alias="SECRET_KEY")
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
    notifications_from_email: str = Field(
        default="no-reply@physihome.com", alias="NOTIFY_FROM_EMAIL"
    )

    admin_emails: list[str] = Field(
        default_factory=lambda: [
            "info@physihome.com",
            "athulnair3096@gmail.com",
        ],
        alias="ADMIN_EMAILS",
    )

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        populate_by_name = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
