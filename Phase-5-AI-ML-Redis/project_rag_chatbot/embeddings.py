"""
============================================================================
 EMBEDDINGS - turn text into vectors, WITH a Redis cache (Cache Layer #2)
============================================================================
This is Concept 2 (embedding cache) turned into reusable project code.

Flow:
    get_embedding(text)
        -> check Redis
        -> HIT : return cached vector instantly
        -> MISS: call the model, store the vector, return it
============================================================================
"""

import hashlib
import json
import random
from functools import lru_cache

import config
from redis_client import r


# ---------------------------------------------------------------------------
# CACHE KEY
# ---------------------------------------------------------------------------
def _embedding_key(text: str) -> str:
    """Unique, stable key per (model, text)."""
    raw = f"{config.EMBEDDING_MODEL}::{text}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"embedding:{config.EMBEDDING_MODEL}:{digest}"


# ---------------------------------------------------------------------------
# THE ACTUAL EMBEDDING CALL (real OR mock)
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def _embedding_model():
    from fastembed import TextEmbedding

    return TextEmbedding(model_name=config.EMBEDDING_MODEL)


def _compute_embedding(text: str) -> list[float]:
    """
    Use a free local embedding model downloaded from Hugging Face.

    If fastembed is not installed yet, fall back to a deterministic
    mock vector so the rest of the Redis pipeline can still run offline.
    """
    try:
        vector = next(_embedding_model().embed([text]))
        if hasattr(vector, "astype"):
            return vector.astype(float).tolist()
        return [float(x) for x in vector]
    except ImportError:
        # --- MOCK PATH (no key needed) ---
        # Seed by the text so the SAME text always gives the SAME vector,
        # exactly like a real embedding model.
        random.seed(text)
        return [round(random.uniform(-1, 1), 4) for _ in range(16)]


# ---------------------------------------------------------------------------
# PUBLIC, CACHE-AWARE FUNCTION
# ---------------------------------------------------------------------------
def get_embedding(text: str) -> tuple[list[float], bool]:
    """
    Return (vector, was_cache_hit).

    We return the hit/miss flag too so the API can report cache stats -
    great for SEEING your cache working.
    """
    key = _embedding_key(text)

    cached = r.get(key)
    if cached is not None:
        return json.loads(cached), True  # HIT

    vector = _compute_embedding(text)     # MISS -> compute
    # Store it. EMBEDDING_CACHE_TTL is None -> no expiry (safe for embeddings).
    if config.EMBEDDING_CACHE_TTL is None:
        r.set(key, json.dumps(vector))
    else:
        r.set(key, json.dumps(vector), ex=config.EMBEDDING_CACHE_TTL)
    return vector, False
