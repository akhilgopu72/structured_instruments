from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    anthropic_api_key: str = ""
    database_url: str = f"sqlite:///{Path(__file__).resolve().parent.parent.parent / 'data' / 'structured_instruments.db'}"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
