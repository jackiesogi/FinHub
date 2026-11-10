"""Settings for FinHub.

Everything that points at another process is a loopback address with a
loopback default, and the host part is not something an env var can widen into
a public bind -- FinHub talks to the CJTrade engine and the ArenaX broker over
127.0.0.1 because that is where they listen, by design.
"""
import logging
import secrets
from pathlib import Path

from pydantic_settings import BaseSettings
from pydantic_settings import SettingsConfigDict

log = logging.getLogger("finhub.config")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ── Auth ──────────────────────────────────────────────────────────────────
    # No fixed default. This key signs session tokens, and the old
    # "temporary_default_key" meant a deployment that forgot to set it ran
    # happily while anyone who had read this file could mint a token for any
    # user. Empty here and filled in below with a random value per process:
    # unset now costs you your sessions on restart, not your account.
    SECRET_KEY: str = ""
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440

    # ── Storage ───────────────────────────────────────────────────────────────
    DATABASE_URL: str = ""          # blank -> sqlite file next to this module

    # ── CJTrade ───────────────────────────────────────────────────────────────
    # Where the checkout lives, so FinHub can start a run.
    CJTRADE_REPO: Path = Path.home() / "Downloads" / "gitrepo" / "CJTrade"
    # The engine's read-only status API (poc/trading_engine/status_api.py).
    ENGINE_STATUS_HOST: str = "127.0.0.1"
    ENGINE_STATUS_PORT: int = 8898
    # The ArenaX broker-side server. 8802 is the backtest instance, which is
    # also the port main2.py has hardcoded, so changing this alone is not
    # enough to move a run -- see README's "Known limits".
    ARENAX_HOST: str = "127.0.0.1"
    ARENAX_PORT: int = 8802
    ARENAX_API_KEY: str = "testkey123"
    # Program used to run CJTrade commands inside its own environment.
    UV_BIN: str = "uv"
    # Where a run's captured stdout/stderr goes.
    RUN_LOG_DIR: Path = Path(__file__).resolve().parent / "run_logs"

    @property
    def engine_base_url(self) -> str:
        return f"http://{self.ENGINE_STATUS_HOST}:{self.ENGINE_STATUS_PORT}"

    @property
    def arenax_base_url(self) -> str:
        return f"http://{self.ARENAX_HOST}:{self.ARENAX_PORT}"


settings = Settings()

if settings.DATABASE_URL.startswith("postgres://"):
    # SQLAlchemy dropped the bare "postgres://" scheme.
    settings.DATABASE_URL = settings.DATABASE_URL.replace("postgres://", "postgresql://", 1)

if not settings.SECRET_KEY:
    settings.SECRET_KEY = secrets.token_urlsafe(48)
    log.warning(
        "SECRET_KEY is not set, so a random one was generated for this process. "
        "Tokens will stop working when FinHub restarts. To keep sessions across "
        "restarts put a value in .env:\n"
        "    python -c 'import secrets; print(f\"SECRET_KEY={secrets.token_urlsafe(48)}\")' >> .env"
    )

settings.RUN_LOG_DIR.mkdir(parents=True, exist_ok=True)
