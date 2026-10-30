import os
from pathlib import Path

# Base directories
BASE_DIR = Path(__file__).resolve().parent.parent.parent
DB_PATH = BASE_DIR / "interview_simulator.db"

# Load .env file manually if exists (avoids extra dependency)
env_path = BASE_DIR / ".env"
if env_path.exists():
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                key_clean = key.strip()
                val_clean = val.strip()
                os.environ[key_clean] = val_clean

PORT = int(os.environ.get("PORT", 8000))
HOST = os.environ.get("HOST", "127.0.0.1")
ENVIRONMENT = os.environ.get("ENVIRONMENT", "development")
SESSION_SECRET = os.environ.get("SESSION_SECRET", "ai_interview_sim_secret_key_v1")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()

raw_model = os.environ.get("LLM_MODEL", "gemini-flash-lite-latest").strip()
# Gracefully map deprecated models to active working flash-lite
if raw_model in ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-3.8-flash"]:
    LLM_MODEL = "gemini-flash-lite-latest"
else:
    LLM_MODEL = raw_model or "gemini-flash-lite-latest"

def has_active_ai_provider() -> bool:
    return bool(GEMINI_API_KEY or OPENAI_API_KEY)
