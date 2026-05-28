import logging
import secrets
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("SignalZero.Config")

class Settings(BaseSettings):
    # App Settings
    ENV: str = "development"
    HOST: str = "127.0.0.1"
    PORT: int = 8007

    # Database Settings - PostgreSQL/Supabase
    # In development, fallback to sqlite:///signalzero.db for simplicity if Postgres URL is not provided
    DATABASE_URL: str = "sqlite:///signalzero.db"

    # Neo4j Settings - AuraDB or local
    NEO4J_URI: str = "bolt://localhost:7687"
    NEO4J_USERNAME: str = "neo4j"
    NEO4J_PASSWORD: str = "neo4j_password"

    # Redis Settings - Upstash or local
    # In development, default to local Redis. If not available, we can mock in memory.
    REDIS_URL: str = "redis://localhost:6379"

    # LLM Settings (Groq / OpenAI)
    GROQ_API_KEY: str = ""
    OPENAI_API_KEY: str = ""

    # Webhook Settings
    SLACK_WEBHOOK_URL: str = ""
    DISCORD_WEBHOOK_URL: str = ""

    # Security: JWT Secret
    JWT_SECRET_KEY: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

# Load settings
try:
    settings = Settings()
except Exception as e:
    logger.warning(f"Error loading settings from environment/dotenv: {e}. Using defaults.")
    settings = Settings(_env_file=None)  # type: ignore[call-arg]

# Resolve and validate JWT Secret according to secure coding guidelines:
# Resolution path: Env Var -> Local File Query -> Ephemeral Random Generation
if not settings.JWT_SECRET_KEY:
    jwt_secret_file = Path("jwt_secret.txt")
    if jwt_secret_file.exists():
        try:
            settings.JWT_SECRET_KEY = jwt_secret_file.read_text(encoding="utf-8").strip()
            logger.info("Loaded JWT secret from jwt_secret.txt")
        except Exception as e:
            logger.error(f"Failed to read jwt_secret.txt: {e}")

    if not settings.JWT_SECRET_KEY:
        settings.JWT_SECRET_KEY = secrets.token_hex(32)
        try:
            jwt_secret_file.write_text(settings.JWT_SECRET_KEY, encoding="utf-8")
            logger.info("Generated and saved new JWT secret to jwt_secret.txt")
        except Exception as e:
            logger.warning(f"Failed to save generated JWT secret to disk: {e}. Using ephemeral key.")

# Detect if we should run in Mock mode for external databases if they aren't reachable
MOCK_DB_MODE = False
if settings.DATABASE_URL == "sqlite:///signalzero.db":
    MOCK_DB_MODE = True
    logger.info("DATABASE_URL is using SQLite default. Running in local SQLite mode.")
