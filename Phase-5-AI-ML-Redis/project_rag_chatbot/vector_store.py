"""
============================================================================
 VECTOR STORE - a tiny in-memory knowledge base + retrieval (Cache Layer #3)
============================================================================
Real projects use Pinecone / Qdrant / Weaviate / pgvector / Redis-Vector.
To keep this project small, we implement a TINY vector store in pure Python.
The concepts are identical:

    1. We embed each document ONCE and keep its vector.
    2. To retrieve, we embed the query and find the closest document vectors
       using cosine similarity.
    3. We CACHE the retrieval result in Redis so repeat queries skip the
       (normally expensive) similarity search - this is Concept 3.

We also implement VERSIONED invalidation: if the knowledge base changes,
bump the version and every cached retrieval is instantly ignored.
============================================================================
"""

import hashlib
import json
import math

import config
from redis_client import r
from embeddings import get_embedding


# ---------------------------------------------------------------------------
# 1. THE KNOWLEDGE BASE  (a few docs about Redis, for the demo)
# ---------------------------------------------------------------------------
KNOWLEDGE_BASE = [
    {"id": "d1", "text": "Redis is an in-memory data store used as a cache, "
                         "database, and message broker. It is extremely fast "
                         "because it keeps data in RAM."},
    {"id": "d2", "text": "A cache stores the results of expensive operations "
                         "so future requests can be served instantly. A cache "
                         "hit means the data was found; a miss means it was not."},
    {"id": "d3", "text": "TTL (time-to-live) tells Redis to automatically "
                         "delete a key after a number of seconds. It is the "
                         "simplest way to keep cached data from going stale."},
    {"id": "d4", "text": "RAG (Retrieval-Augmented Generation) retrieves "
                         "relevant documents from a knowledge base and feeds "
                         "them to an LLM so answers are grounded in real data."},
    {"id": "d5", "text": "Cache invalidation is the hard problem of removing "
                         "or updating cached data when the source changes. "
                         "Common tools are TTL expiry and key versioning."},
]

# Pre-compute (and cache, via get_embedding) the vector for every document.
# In a real system this indexing step runs once when documents are added.
_INDEX: list[dict] = []


def build_index() -> None:
    """Embed every document once. Called at app startup."""
    global _INDEX
    _INDEX = []
    for doc in KNOWLEDGE_BASE:
        vector, _ = get_embedding(doc["text"])
        _INDEX.append({**doc, "vector": vector})


# ---------------------------------------------------------------------------
# 2. COSINE SIMILARITY  (how "close" two vectors are, from -1 to 1)
# ---------------------------------------------------------------------------
def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Higher = more similar. 1.0 means identical direction."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


# ---------------------------------------------------------------------------
# 3. VERSIONED INVALIDATION
# ---------------------------------------------------------------------------
_KB_VERSION_KEY = "rag:kb_version"


def _kb_version() -> int:
    v = r.get(_KB_VERSION_KEY)
    if v is None:
        r.set(_KB_VERSION_KEY, 1)
        return 1
    return int(v)


def bump_kb_version() -> int:
    """Call after changing KNOWLEDGE_BASE; instantly invalidates the cache."""
    return r.incr(_KB_VERSION_KEY)


# ---------------------------------------------------------------------------
# 4. CACHE-AWARE RETRIEVAL
# ---------------------------------------------------------------------------
def _retrieval_key(query: str, top_k: int) -> str:
    # The version is baked into the key -> bumping it changes every key.
    raw = f"v{_kb_version()}::k{top_k}::{query}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"rag:retrieval:{digest}"


def _search(query: str, top_k: int) -> list[dict]:
    """The 'expensive' similarity search (small here, but real at scale)."""
    query_vec, _ = get_embedding(query)
    scored = []
    for doc in _INDEX:
        score = _cosine_similarity(query_vec, doc["vector"])
        scored.append({"id": doc["id"], "text": doc["text"],
                       "score": round(score, 4)})
    # Sort by similarity, highest first, and keep the top_k.
    scored.sort(key=lambda d: d["score"], reverse=True)
    return scored[:top_k]


def retrieve(query: str, top_k: int | None = None) -> tuple[list[dict], bool]:
    """
    Return (documents, was_cache_hit).

    Checks Redis first (retrieval cache). On a miss it runs the search and
    stores the result with a short TTL as a safety net against staleness.
    """
    top_k = top_k or config.TOP_K
    key = _retrieval_key(query, top_k)

    cached = r.get(key)
    if cached is not None:
        return json.loads(cached), True  # HIT

    docs = _search(query, top_k)          # MISS
    r.set(key, json.dumps(docs), ex=config.RETRIEVAL_CACHE_TTL)
    return docs, False
