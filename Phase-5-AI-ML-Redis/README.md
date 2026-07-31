# Phase 5 — AI/ML Redis (End-to-End)

Caching patterns that make AI applications **fast, cheap, and production-ready**.
This is the complete Phase 5 of your Redis roadmap: four AI/ML caching concepts
plus a fully-working **cached RAG chatbot** that combines them.

Embeddings use a free Hugging Face Sentence Transformers model. The LLM runs
offline with a mock response by default, or against **Groq** if you set a key.

> 📘 **Start with `Phase5_Handbook.pdf`.** It explains every concept in this
> package from scratch. Read it top to bottom and you'll understand all of Phase 5.

---

## 📂 What's in this package

```
phase5-ai-ml-redis/
├── README.md                 ← you are here
├── Phase5_Handbook.pdf       ← the illustrated handbook (READ THIS FIRST)
│
├── concepts/                 ← the 4 caching concepts, each standalone & runnable
│   ├── 01_llm_cache.py           LLM response cache
│   ├── 02_embedding_cache.py     Embedding cache (single + batch)
│   ├── 03_rag_cache.py           RAG retrieval cache + invalidation
│   └── 04_feature_store_cache.py Online feature store cache
│
└── project_rag_chatbot/      ← Project 4: cached RAG chatbot (FastAPI)
    ├── config.py                 all settings (env-driven)
    ├── redis_client.py           one shared Redis connection
    ├── embeddings.py             Cache Layer 2 (embeddings)
    ├── vector_store.py           Cache Layer 3 (retrieval) + versioned invalidation
    ├── llm.py                    Cache Layer 1 (LLM responses)
    ├── rag_pipeline.py           ties all 3 layers together
    ├── main.py                   FastAPI endpoints
    ├── requirements.txt
    ├── docker-compose.yml        one-command Redis
    └── .env.example              copy to .env to customize
```

Every file is heavily commented in English so you can learn by reading the code.

---

## 🚀 Quick start

### 1. Start Redis

```bash
# Option A — Docker (recommended), from inside project_rag_chatbot/
docker compose up -d

# Option B — local install
redis-server --daemonize yes
redis-cli ping        # → PONG
```

### 2. Run the four concept scripts

```bash
pip install redis
cd concepts
python 01_llm_cache.py            # watch MISS (slow) → HIT (instant)
python 02_embedding_cache.py      # single + batch caching
python 03_rag_cache.py            # retrieval cache + invalidation
python 04_feature_store_cache.py  # write side / read side
```

### 3. Run the RAG chatbot

```bash
cd project_rag_chatbot
pip install -r requirements.txt
uvicorn main:app --reload
# open http://localhost:8000/docs
```

### 4. See caching happen

```bash
# Call the SAME question twice and compare the "cache" field.
curl -X POST localhost:8000/chat -H "Content-Type: application/json" \
     -d '{"question":"What is TTL?"}'
```

| Call | `retrieval_cache_hit` | `llm_cache_hit` | Speed |
|------|----------------------|-----------------|-------|
| 1st  | `false`              | `false`         | slower |
| 2nd  | `true`               | `true`          | much faster |

Then invalidate the retrieval cache and watch it flip back:

```bash
curl -X POST localhost:8000/admin/reindex   # bump KB version
curl localhost:8000/admin/stats             # count keys per cache layer
```

---

## 🧠 The four concepts at a glance

| # | Cache | Caches on a miss? | Stale risk | Invalidation |
|---|-------|:-----------------:|:----------:|--------------|
| 1 | **LLM response** | ✅ | medium | TTL |
| 2 | **Embedding** | ✅ | none | none needed |
| 3 | **Retrieval** | ✅ | high | TTL + versioning |
| 4 | **Feature store** | ❌ (pre-pushed) | time-bound | TTL / refresh |

All of them are the **Cache-Aside** pattern from Phase 1:
*look in Redis first → on a miss do the expensive work → store the result.*

---

## 🔌 Using real Groq + Hugging Face embeddings

By default the LLM uses a deterministic **mock** response so it runs with zero
LLM setup and zero cost. Embeddings use the free Hugging Face model configured
by `EMBEDDING_MODEL`. To switch the LLM to Groq:

```bash
cd project_rag_chatbot
cp .env.example .env
# edit .env and set:  GROQ_API_KEY=your_groq_key
```

No code changes needed — `config.py` detects the key and the same pipeline
starts calling Groq for completions while keeping embeddings on Hugging Face.

---

## ✅ Requirements

- Python 3.10+
- Redis (via Docker or a local install)
- `pip install -r project_rag_chatbot/requirements.txt`

---

## ➡️ Next: Phase 6 — Agentic AI Redis

You've cached the *results* of AI work. Phase 6 uses Redis for **agent memory,
conversation state, and checkpointing** — a shared, durable brain for
multi-agent systems.
