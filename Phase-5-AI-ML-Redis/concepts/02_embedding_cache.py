"""
============================================================================
 PHASE 5 - CONCEPT 2: EMBEDDING CACHE
============================================================================

WHAT IS AN EMBEDDING? (30-second refresher)
-------------------------------------------
An embedding turns a piece of text into a list of numbers (a vector) that
captures its MEANING. Similar texts get similar vectors.

    "dog"   -> [0.12, -0.44, 0.98, ...]   (e.g. 1536 numbers)
    "puppy" -> [0.13, -0.41, 0.95, ...]   (very close to "dog")
    "car"   -> [0.88,  0.02, -0.31, ...]  (far away)

We use embeddings for search, RAG, clustering, recommendations, etc.

WHY CACHE THEM?
---------------
Generating an embedding also costs money + time (it's a model call).
And here's the key insight:

    THE SAME TEXT ALWAYS PRODUCES THE SAME EMBEDDING.

Embeddings are deterministic. So re-embedding "What is Redis?" a hundred
times is 100% waste. This makes embeddings the PERFECT thing to cache -
even better than LLM answers, because there is zero risk of staleness
(the mapping text->vector never changes for a given model).

THE IDEA
--------
    Text  ->  Redis  ->  (miss?)  ->  Embedding model  ->  store  ->  vector
    Text  ->  Redis  ->  (hit!)   ->  vector   (no model call)

STORAGE NOTE
------------
A vector is a list of floats. Redis stores strings/bytes, so we serialize
the vector to JSON before storing and parse it back on read. (In a real
high-performance system you'd store raw float32 bytes to save space, but
JSON is clearer for learning.)
============================================================================
"""

import hashlib
import json
import time
import random

import redis


r = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)


# ---------------------------------------------------------------------------
# 1. CACHE KEY = hash of (text + embedding model name)
# ---------------------------------------------------------------------------
def make_embedding_key(text: str, model: str) -> str:
    """
    We include the model name because different embedding models produce
    different vectors (and even different vector SIZES) for the same text.
    A Hugging Face vector and a local/mock vector must never collide.
    """
    raw = f"{model}::{text}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"embedding:{model}:{digest}"


# ---------------------------------------------------------------------------
# 2. THE (FAKE) EMBEDDING MODEL
# ---------------------------------------------------------------------------
def embed_text(text: str, model: str) -> list[float]:
    """
    Pretend to call an embedding model. Real ones return 384-3072 floats.
    We return a small fake 8-dim vector, seeded by the text so the SAME
    text always yields the SAME vector (just like a real model).
    """
    print(f"   [EMBED] Real model call (slow)  text='{text[:30]}...'")
    time.sleep(1)  # simulate latency
    random.seed(text)  # deterministic: same text -> same numbers
    return [round(random.uniform(-1, 1), 4) for _ in range(8)]


# ---------------------------------------------------------------------------
# 3. CACHE-AWARE EMBEDDING FUNCTION
# ---------------------------------------------------------------------------
def get_embedding(
    text: str,
    model: str = "BAAI/bge-small-en-v1.5",
) -> list[float]:
    """
    Return the embedding for `text`, using Redis to avoid recomputation.

    NOTE: We usually do NOT set a TTL here. Because text->vector never
    changes for a fixed model, this data is safe to keep "forever" (until
    Redis evicts it under memory pressure using an LRU/LFU policy - remember
    eviction policies from Phase 1!).
    """
    key = make_embedding_key(text, model)

    # --- CACHE READ ---
    cached = r.get(key)
    if cached is not None:
        print("   [CACHE HIT]  vector loaded from Redis")
        return json.loads(cached)  # JSON string -> Python list

    # --- CACHE MISS -> compute + store ---
    print("   [CACHE MISS] computing embedding")
    vector = embed_text(text, model)
    r.set(key, json.dumps(vector))  # Python list -> JSON string
    return vector


# ---------------------------------------------------------------------------
# 4. BONUS: BATCH EMBEDDING WITH CACHE
# ---------------------------------------------------------------------------
# In real pipelines you embed MANY texts at once. A smart cache checks which
# ones are already cached, and only sends the *missing* ones to the model.
def get_embeddings_batch(
    texts: list[str],
    model: str = "BAAI/bge-small-en-v1.5",
) -> dict[str, list[float]]:
    """
    Efficiently embed a list of texts:
      1. Ask Redis for all of them at once (MGET = one round trip).
      2. Compute only the misses.
      3. Store the newly computed ones.
    """
    keys = [make_embedding_key(t, model) for t in texts]

    # MGET fetches many keys in a single network call - far faster than
    # calling GET in a loop (fewer round trips = big win at scale).
    cached_values = r.mget(keys)

    results: dict[str, list[float]] = {}
    missing: list[str] = []

    for text, cached in zip(texts, cached_values):
        if cached is not None:
            results[text] = json.loads(cached)  # hit
        else:
            missing.append(text)                # needs computing

    print(f"   [BATCH] {len(texts) - len(missing)} hits, {len(missing)} misses")

    # Compute + store only the missing ones.
    for text in missing:
        vector = embed_text(text, model)
        results[text] = vector
        r.set(make_embedding_key(text, model), json.dumps(vector))

    return results


# ---------------------------------------------------------------------------
# 5. DEMO  ->  run:  python 02_embedding_cache.py
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("\n--- Single embedding, twice ---")
    t0 = time.time()
    v1 = get_embedding("What is Redis?")
    print(f"1st (miss) took {time.time() - t0:.2f}s")

    t0 = time.time()
    v2 = get_embedding("What is Redis?")
    print(f"2nd (hit)  took {time.time() - t0:.2f}s")

    # Proof that caching returned the identical vector:
    assert v1 == v2, "cached vector should equal the computed one"
    print("Vectors identical:", v1 == v2)

    print("\n--- Batch embedding (some cached, some new) ---")
    texts = ["What is Redis?", "What is caching?", "What is RAG?"]
    # "What is Redis?" is already cached from above -> should be a hit.
    embeddings = get_embeddings_batch(texts)
    print("Got vectors for:", list(embeddings.keys()))
