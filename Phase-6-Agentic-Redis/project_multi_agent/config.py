"""
============================================================================
 CONFIG - all tunable settings in one place (read from environment)
============================================================================
"""

import os

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - keeps config importable before deps install
    load_dotenv = None

if load_dotenv is not None:
    load_dotenv()

# --- Redis connection -------------------------------------------------------
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB = int(os.getenv("REDIS_DB", "0"))

# --- Memory / TTL settings --------------------------------------------------
CONVERSATION_TTL = int(os.getenv("CONVERSATION_TTL", "3600"))   # 1 hour idle
CONVERSATION_WINDOW = int(os.getenv("CONVERSATION_WINDOW", "20"))  # last N turns

# --- Model settings ---------------------------------------------------------
LLM_MODEL = os.getenv("LLM_MODEL", "llama-3.3-70b-versatile")

# --- Groq (optional) --------------------------------------------------------
# Leave empty to run fully offline with deterministic MOCK agents.
# Set a real key to make agents call Groq (same code path).
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
USE_REAL_GROQ = bool(GROQ_API_KEY)
