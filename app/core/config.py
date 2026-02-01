from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "PhysiHome"
    environment: Literal["dev", "prod", "test"] = "dev"
    secret_key: str = "CHANGE_ME"  # will be overridden via env

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    return Settings()
