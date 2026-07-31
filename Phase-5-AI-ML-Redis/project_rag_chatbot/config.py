"""
============================================================================
 CONFIG - all tunable settings in one place
============================================================================
Keeping configuration in ONE file (read from environment variables) is a
production habit: you never hard-code secrets or hosts inside your logic.
The .env.example file shows which variables you can set.
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

# --- Cache TTLs (Time-To-Live, in seconds) ---------------------------------
# These control how long each cache layer keeps its data before Redis
# auto-deletes it. Tune them based on how often your data changes.
LLM_CACHE_TTL = int(os.getenv("LLM_CACHE_TTL", "3600"))          # 1 hour
RETRIEVAL_CACHE_TTL = int(os.getenv("RETRIEVAL_CACHE_TTL", "300"))  # 5 min
# Embeddings never go stale for a fixed model, so we keep them "forever"
# (None = no expiry; Redis eviction policy handles memory pressure).
EMBEDDING_CACHE_TTL = None

# --- Model settings ---------------------------------------------------------
LLM_MODEL = os.getenv("LLM_MODEL", "llama-3.3-70b-versatile")
EMBEDDING_MODEL = os.getenv(
    "EMBEDDING_MODEL",
    "BAAI/bge-small-en-v1.5",
)
TOP_K = int(os.getenv("TOP_K", "3"))  # how many docs to retrieve per query

# --- Groq (optional) --------------------------------------------------------
# If this key is set, the app calls Groq for the LLM response.
# If it is empty, the app falls back to a fast offline mock answer so you can
# run and learn the whole pipeline WITHOUT any API key or cost.
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
USE_REAL_GROQ = bool(GROQ_API_KEY)
