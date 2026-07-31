"""
============================================================================
 MAIN - FastAPI web app exposing the cached RAG chatbot
============================================================================
Run it:
    uvicorn main:app --reload

Then open the interactive docs in your browser:
    http://localhost:8000/docs

Endpoints:
    GET  /health        -> is the app + Redis alive?
    POST /chat          -> ask a question, get a cached RAG answer
    POST /admin/reindex -> simulate a knowledge-base change (invalidates cache)
    GET  /admin/stats   -> see how many keys each cache layer holds
============================================================================
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import BaseModel

import vector_store
import redis_client
from rag_pipeline import answer_question


# ---------------------------------------------------------------------------
# STARTUP: build the vector index once when the server boots
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    # This runs ONCE at startup. We embed all documents (cached) so the app
    # is ready to answer immediately.
    vector_store.build_index()
    yield
    # (nothing to clean up on shutdown for this demo)


app = FastAPI(title="Cached RAG Chatbot (Phase 5)", lifespan=lifespan)


# ---------------------------------------------------------------------------
# REQUEST/RESPONSE SCHEMAS  (Pydantic validates input automatically)
# ---------------------------------------------------------------------------
class ChatRequest(BaseModel):
    question: str


@app.get("/")
def root():
    return {
        "message": "Cached RAG Chatbot is running.",
        "docs": "/docs",
        "health": "/health",
        "chat": "POST /chat",
    }


# ---------------------------------------------------------------------------
# HEALTH CHECK
# ---------------------------------------------------------------------------
@app.get("/health")
def health():
    """Confirms the API is up and whether Redis is reachable."""
    return {"status": "ok", "redis_connected": redis_client.ping()}


# ---------------------------------------------------------------------------
# CHAT  -  the main endpoint
# ---------------------------------------------------------------------------
@app.post("/chat")
def chat(req: ChatRequest):
    """
    Ask the chatbot a question.

    Try calling this TWICE with the same question:
      - 1st call: cache misses, slower.
      - 2nd call: cache hits, much faster, and cache.*_hit will be true.
    """
    return answer_question(req.question)


# ---------------------------------------------------------------------------
# ADMIN: simulate a knowledge-base update -> invalidate the retrieval cache
# ---------------------------------------------------------------------------
@app.post("/admin/reindex")
def reindex():
    """
    Pretend we added/edited documents. We bump the KB version, which
    instantly makes every cached retrieval result obsolete (see Concept 3).
    """
    new_version = vector_store.bump_kb_version()
    return {"message": "Knowledge base reindexed; retrieval cache invalidated.",
            "kb_version": new_version}


# ---------------------------------------------------------------------------
# ADMIN: quick cache statistics (count keys per layer)
# ---------------------------------------------------------------------------
@app.get("/admin/stats")
def stats():
    """
    Count how many keys live in each cache layer. Uses SCAN (not KEYS) so it
    is safe to run on a production Redis with many keys.
    """
    def count(pattern: str) -> int:
        total = 0
        for _ in redis_client.r.scan_iter(match=pattern, count=100):
            total += 1
        return total

    return {
        "llm_response_keys": count("llm:response:*"),
        "embedding_keys": count("embedding:*"),
        "retrieval_keys": count("rag:retrieval:*"),
    }
