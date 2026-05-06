import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    """
    Application settings and environment variable management.
    Values are loaded from environment variables or a local .env file.
    """
    # [1] Database URL with an automatic fix for Render (postgres -> postgresql)
    DATABASE_URL: str = ""

    # [2] Secret Key for JWT authentication
    SECRET_KEY: str = "temporary_default_key"

    class Config:
        env_file = ".env"

    # Post-process the DATABASE_URL to ensure SQLAlchemy compatibility
    def __init__(self, **values):
        super().__init__(**values)
        if self.DATABASE_URL.startswith("postgres://"):
            self.DATABASE_URL = self.DATABASE_URL.replace("postgres://", "postgresql://", 1)

settings = Settings()
