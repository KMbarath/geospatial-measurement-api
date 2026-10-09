"""Application settings, overridable through environment variables or a .env file."""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="GEO_", extra="ignore")

    database_url: str = "sqlite:///./data/app.db"
    storage_dir: Path = Path("./data/uploads")

    # Upload / processing guard rails
    max_upload_mb: int = 50
    max_uncompressed_mb: int = 500  # protects against zip bombs
    max_archive_members: int = 1000
    max_features: int = 200_000

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def max_uncompressed_bytes(self) -> int:
        return self.max_uncompressed_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
