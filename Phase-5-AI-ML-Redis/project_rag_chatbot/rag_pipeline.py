r"""
============================================================================
 RAG PIPELINE - the conductor that ties the 3 caches together
============================================================================
This is the heart of Project 4. It runs the full Retrieval-Augmented
Generation flow and shows exactly where each of the THREE cache layers sits:

    User question
         |
         v
   [ Cache Layer 3: RETRIEVAL CACHE ]  (vector_store.retrieve)
         |   \__ internally uses [ Cache Layer 2: EMBEDDING CACHE ]
         v
   retrieved documents
         |
         v
   build prompt (question + documents)
         |
         v
   [ Cache Layer 1: LLM RESPONSE CACHE ]  (llm.generate_answer)
         |
         v
   final answer  (+ timing + which caches hit)

The return value includes a "cache" report so the API can SHOW you which
layers were hits vs misses on each request. That visibility is the best way
to build intuition about how caching behaves.
============================================================================
"""

import time

import vector_store
import llm


def answer_question(question: str) -> dict:
    """
    Run the full cached RAG pipeline for one question.
    Returns a dict with the answer, timing, and per-layer cache stats.
    """
    started = time.time()

    # --- STEP 1: RETRIEVE (uses retrieval cache + embedding cache inside) ---
    documents, retrieval_hit = vector_store.retrieve(question)

    # --- STEP 2: BUILD THE PROMPT from question + retrieved docs ---
    prompt = llm.build_prompt(question, documents)

    # --- STEP 3: GENERATE (uses the LLM response cache) ---
    answer, llm_hit = llm.generate_answer(prompt)

    elapsed_ms = round((time.time() - started) * 1000, 1)

    return {
        "question": question,
        "answer": answer,
        "sources": [{"id": d["id"], "score": d["score"]} for d in documents],
        "elapsed_ms": elapsed_ms,
        "cache": {
            # True = we avoided the expensive work on this layer this time.
            "retrieval_cache_hit": retrieval_hit,
            "llm_cache_hit": llm_hit,
        },
    }
