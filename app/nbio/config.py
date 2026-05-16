from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    db_path: str = "/data/app.db"
    baby_name: str = "Baby"
    tz: str = "Europe/London"

    dup_window_seconds: int = 120
    sse_replay_cap: int = 500


settings = Settings()
