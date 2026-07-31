"""
============================================================================
 PHASE 5 - CONCEPT 3: RAG RETRIEVAL CACHE
============================================================================

WHAT IS RAG? (Retrieval-Augmented Generation)
---------------------------------------------
Instead of hoping the LLM "knows" the answer, we:
  1. RETRIEVE relevant documents from a knowledge base (a Vector DB).
  2. Stuff those documents into the prompt as context.
  3. Ask the LLM to answer USING that context.

This is how you make a chatbot that answers from YOUR data (company docs,
product manuals, etc.) instead of hallucinating.

    Question
       |
       v
    [Retriever]  -->  Vector DB  -->  top-k matching documents
       |
       v
    documents + question  -->  LLM  -->  grounded answer

WHERE'S THE EXPENSIVE PART?
---------------------------
The RETRIEVAL step is a similarity search over possibly millions of
vectors. It costs CPU/time and, for hosted vector DBs, money per query.

And again: the SAME question retrieves the SAME documents (as long as the
knowledge base hasn't changed). So we cache the retrieval results.

    Retriever  ->  Redis  ->  (miss?)  ->  Vector DB  ->  store  ->  docs
    Retriever  ->  Redis  ->  (hit!)   ->  docs   (skip the Vector DB)

THE CACHE INVALIDATION PROBLEM (the hard part - from Phase 4!)
-------------------------------------------------------------
Unlike embeddings, retrieval results CAN go stale: if you add or update
documents in the knowledge base, old cached results become wrong.

Two common defenses (both shown below):
  1. TTL  -> results expire automatically after N seconds/minutes.
  2. VERSIONING -> put a "knowledge base version" number in the cache key.
     When you update the KB, bump the version and ALL old keys are instantly
     orphaned (ignored) - a clean, instant, global invalidation trick.
============================================================================
"""

import hashlib
import json
import time

import redis


r = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)


# ---------------------------------------------------------------------------
# 1. KNOWLEDGE BASE VERSION
# ---------------------------------------------------------------------------
# Store a single "version" number in Redis. Every cache key includes it.
# To invalidate the ENTIRE retrieval cache at once (e.g. after re-indexing
# your documents), just INCR this number. Old keys still exist but will
# never be looked up again, and TTL will eventually clean them up.
KB_VERSION_KEY = "rag:kb_version"


def get_kb_version() -> int:
    version = r.get(KB_VERSION_KEY)
    if version is None:
        r.set(KB_VERSION_KEY, 1)  # initialize on first run
        return 1
    return int(version)


def bump_kb_version() -> int:
    """Call this AFTER you add/update/delete documents in the knowledge base."""
    new_version = r.incr(KB_VERSION_KEY)  # atomic +1
    print(f"   [INVALIDATE] Knowledge base bumped to version {new_version}")
    print("               All previously cached retrievals are now ignored.")
    return new_version


# ---------------------------------------------------------------------------
# 2. CACHE KEY = hash of (query + top_k + kb_version)
# ---------------------------------------------------------------------------
def make_retrieval_key(query: str, top_k: int) -> str:
    version = get_kb_version()
    raw = f"v{version}::k{top_k}::{query}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    # The version in the key is what makes bump_kb_version() work: after a
    # bump, the SAME query produces a DIFFERENT key -> guaranteed cache miss.
    return f"rag:retrieval:{digest}"


# ---------------------------------------------------------------------------
# 3. THE (FAKE) VECTOR DB SEARCH
# ---------------------------------------------------------------------------
def search_vector_db(query: str, top_k: int) -> list[dict]:
    """
    Pretend to run a similarity search. Real implementations query Pinecone,
    Weaviate, Qdrant, pgvector, Redis Vector, etc. This is slow + costly.
    """
    print(f"   [VECTOR DB] similarity search for '{query}' (slow)")
    time.sleep(1.5)  # simulate search latency
    # Return fake "documents" with a relevance score.
    return [
        {"id": f"doc_{i}", "text": f"Relevant passage {i} about '{query}'",
         "score": round(1.0 - i * 0.1, 2)}
        for i in range(top_k)
    ]


# ---------------------------------------------------------------------------
# 4. CACHE-AWARE RETRIEVER
# ---------------------------------------------------------------------------
def retrieve(query: str, top_k: int = 3, ttl_seconds: int = 300) -> list[dict]:
    """
    Retrieve top-k documents for a query, using Redis to skip repeat searches.

    ttl_seconds=300 (5 min) is a SAFETY NET: even if you forget to bump the
    KB version, cached results self-destruct after 5 minutes. Combine short
    TTL (safety net) + versioning (instant purge) for robust invalidation.
    """
    key = make_retrieval_key(query, top_k)

    # --- CACHE READ ---
    cached = r.get(key)
    if cached is not None:
        print("   [CACHE HIT]  documents served from Redis (Vector DB skipped)")
        return json.loads(cached)

    # --- CACHE MISS -> real search + store ---
    print("   [CACHE MISS] querying the Vector DB")
    documents = search_vector_db(query, top_k)
    r.set(key, json.dumps(documents), ex=ttl_seconds)
    return documents


# ---------------------------------------------------------------------------
# 5. DEMO  ->  run:  python 03_rag_cache.py
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    q = "How does Redis replication work?"

    print("\n--- 1st retrieval (MISS, slow) ---")
    t0 = time.time()
    docs = retrieve(q)
    print(f"Got {len(docs)} docs in {time.time() - t0:.2f}s")

    print("\n--- 2nd retrieval, same query (HIT, instant) ---")
    t0 = time.time()
    docs = retrieve(q)
    print(f"Got {len(docs)} docs in {time.time() - t0:.2f}s")

    print("\n--- Now imagine we re-indexed the knowledge base ---")
    bump_kb_version()  # <-- invalidate everything

    print("\n--- 3rd retrieval, same query (MISS again, because version changed) ---")
    t0 = time.time()
    docs = retrieve(q)
    print(f"Got {len(docs)} docs in {time.time() - t0:.2f}s")

    # TAKEAWAY:
    # Caching retrieval is a huge speedup, BUT retrieval can go stale, so you
    # MUST have an invalidation strategy. TTL + versioning together are the
    # production-grade answer.
