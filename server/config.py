import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

_raw_secret = os.environ.get("JWT_SECRET", "")
if not _raw_secret or _raw_secret == "dev-secret-change-me":
    import sys
    if os.environ.get("PARV_ENV") == "production":
        raise RuntimeError("JWT_SECRET must be set in production. Generate one: python3 -c \"import secrets; print(secrets.token_hex(32))\"")
    _raw_secret = _raw_secret or "dev-secret-change-me"
JWT_SECRET: str = _raw_secret
JWT_ALGORITHM: str = os.environ.get("JWT_ALGORITHM", "HS256")
JWT_EXPIRE_MINUTES: int = int(os.environ.get("JWT_EXPIRE_MINUTES", "60"))

ANTHROPIC_API_KEY: str = os.environ.get("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY: str = os.environ.get("OPENAI_API_KEY", "")

OLLAMA_BASE_URL: str = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL: str = os.environ.get("OLLAMA_MODEL", "llama3.2:7b-instruct-q4_K_M")

MQTT_HOST: str = os.environ.get("MQTT_HOST", "localhost")
MQTT_PORT: int = int(os.environ.get("MQTT_PORT", "1883"))

REDIS_URL: str = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

TAILSCALE_HOSTNAME: str = os.environ.get("TAILSCALE_HOSTNAME", "localhost")
ENV: str = os.environ.get("PARV_ENV", "development")  # set to "production" on Windows laptop
