"""
Environment-driven settings using pydantic-settings.
"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    SUPABASE_URL: str = "https://rhckohqfbvkeinsqyesh.supabase.co"
    SUPABASE_SERVICE_ROLE_KEY: str
    SUPABASE_ANON_KEY: str
    JWT_SECRET: str = "placeholder-jwt-secret-replace-in-phase-2"
    CORS_ORIGINS: str = "*"

    @property
    def cors_origin_list(self) -> list[str]:
        """Parse comma-separated origins into a list."""
        if self.CORS_ORIGINS.strip() == "*":
            return ["*"]
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
