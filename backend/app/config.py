from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "postgresql+asyncpg://sentinell:sentinell@localhost:5432/sentinell"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # OpenAI
    OPENAI_API_KEY: str = ""

    # JWT
    JWT_SECRET_KEY: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 480

    # GitHub
    GITHUB_TOKEN: str = ""

    # Slack
    SLACK_WEBHOOK_URL: str = ""

    # SMTP
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_EMAIL: str = "alerts@sentinellai.dev"

    # Frontend
    FRONTEND_URL: str = "http://localhost:3000"

    # Testing / Integrity
    SKIP_INTEGRITY_CHECK: bool = False

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
