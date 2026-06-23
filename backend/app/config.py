from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://sprintmind:sprintmind@localhost:5432/sprintmind"
    secret_key: str = "dev-secret-change-in-production"
    access_token_expire_minutes: int = 1440
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: str = "http://localhost:3000,http://localhost:5173,http://localhost:3001"
    upload_dir: str = "/app/data/uploads"
    frontend_url: str = "http://localhost:3001"

    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_publishable_key: str = ""

    stripe_price_pro: str = ""
    stripe_price_enterprise: str = ""

    ollama_base_url: str = "http://ollama:11434"
    ollama_model: str = "llama3.2"
    workflow_workspace: str = "/app/data/workspace"

    @property
    def ollama_enabled(self) -> bool:
        return bool(self.ollama_base_url)

    @property
    def effective_stripe_secret_key(self) -> str:
        if self.stripe_secret_key and self.stripe_secret_key.startswith("sk_"):
            return self.stripe_secret_key
        if self.secret_key.startswith("sk_"):
            return self.secret_key
        return self.stripe_secret_key

    @property
    def effective_jwt_secret(self) -> str:
        if self.secret_key.startswith("sk_"):
            return "dev-jwt-secret-change-me"
        return self.secret_key

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def stripe_enabled(self) -> bool:
        key = self.effective_stripe_secret_key
        return bool(key and key.startswith("sk_"))


settings = Settings()
