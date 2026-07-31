"""
============================================================================
 LLM - generate an answer from context, WITH a Redis cache (Cache Layer #1)
============================================================================
This is Concept 1 (LLM response cache) as project code.

In RAG, the LLM prompt = the user's question + the retrieved documents.
We cache on a hash of that FULL prompt, so identical (question + context)
pairs are answered instantly without a second LLM call.
============================================================================
"""

import hashlib
import json

import config
from redis_client import r


# ---------------------------------------------------------------------------
# CACHE KEY  (hash of the full prompt + model)
# ---------------------------------------------------------------------------
def _llm_key(prompt: str) -> str:
    raw = json.dumps({"model": config.LLM_MODEL, "prompt": prompt},
                     sort_keys=True)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"llm:response:{digest}"


# ---------------------------------------------------------------------------
# BUILD THE RAG PROMPT
# ---------------------------------------------------------------------------
def build_prompt(question: str, documents: list[dict]) -> str:
    """
    Combine retrieved documents + the question into one prompt.
    We instruct the model to answer ONLY from the context, which is what
    keeps RAG answers grounded instead of hallucinated.
    """
    context = "\n".join(f"- {d['text']}" for d in documents)
    return (
        "Answer the question using ONLY the context below. "
        "If the answer is not in the context, say you don't know.\n\n"
        f"Context:\n{context}\n\n"
        f"Question: {question}\n"
        "Answer:"
    )


# ---------------------------------------------------------------------------
# THE ACTUAL LLM CALL (real OR mock)
# ---------------------------------------------------------------------------
def _call_llm(prompt: str) -> str:
    if config.USE_REAL_GROQ:
        # --- REAL PATH ---
        from groq import Groq

        client = Groq(api_key=config.GROQ_API_KEY)
        resp = client.chat.completions.create(
            model=config.LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,  # deterministic -> safe to cache
        )
        return resp.choices[0].message.content
    else:
        # --- MOCK PATH (no key needed) ---
        # Return a canned answer that stitches the retrieved context together,
        # so you can see the full pipeline working offline.
        # (Everything after "Context:" up to "Question:" is the context.)
        ctx = prompt.split("Context:\n", 1)[-1].split("\n\nQuestion:", 1)[0]
        first_point = ctx.strip().split("\n")[0].lstrip("- ")
        return f"[MOCK ANSWER] Based on the retrieved context: {first_point}"


# ---------------------------------------------------------------------------
# PUBLIC, CACHE-AWARE FUNCTION
# ---------------------------------------------------------------------------
def generate_answer(prompt: str) -> tuple[str, bool]:
    """Return (answer, was_cache_hit)."""
    key = _llm_key(prompt)

    cached = r.get(key)
    if cached is not None:
        return cached, True  # HIT -> no LLM call, no cost

    answer = _call_llm(prompt)  # MISS -> real work
    r.set(key, answer, ex=config.LLM_CACHE_TTL)
    return answer, False
