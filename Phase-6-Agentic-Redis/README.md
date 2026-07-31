# Phase 6 — Agentic AI Redis (End-to-End)

Give AI agents a **durable, shared brain**: memory, state, checkpoints, and
shared coordination — all powered by Redis. This is the complete Phase 6 of
your Redis roadmap: four agentic-AI concepts plus a **six-agent, LangGraph-style
multi-agent system** that ties them together.

Everything runs **offline with no API key** (deterministic mock agents), or
against **real Groq** if you set a key — the same code, either way.

> 📘 **Start with `Phase6_Handbook.pdf`.** It explains every concept from
> scratch. Read it top to bottom and you'll understand all of Phase 6.

---

## 📂 What's in this package

```
phase6-agentic-redis/
├── README.md                 ← you are here
├── Phase6_Handbook.pdf       ← the illustrated handbook (READ THIS FIRST)
│
├── concepts/                 ← the 4 pillars, each standalone & runnable
│   ├── 01_agent_memory.py        Short-term / conversation memory (List)
│   ├── 02_state_management.py    Shared task state between agents (Hash)
│   ├── 03_checkpointing.py       Resume long runs after a crash (append-only List)
│   └── 04_shared_memory.py       Blackboard + distributed lock + Pub/Sub
│
└── project_multi_agent/      ← Project 5: 6-agent system (LangGraph-style)
    ├── config.py                 all settings (env-driven)
    ├── redis_client.py           one shared Redis connection
    ├── memory.py                 Pillar 1 — conversation memory
    ├── state.py                  Pillar 2 — shared AgentState
    ├── checkpointer.py           Pillar 3 — checkpoints & resume
    ├── shared_memory.py          Pillar 4 — blackboard, locks, pub/sub
    ├── agents.py                 the 6 agents (Planner…Reviewer)
    ├── graph.py                  the orchestrator (nodes, edges, loop, resume)
    ├── run_cli.py                CLI demo: full run + crash/resume
    ├── main.py                   FastAPI endpoints
    ├── requirements.txt
    ├── docker-compose.yml        one-command Redis
    └── .env.example              copy to .env to customize
```

Every file is heavily commented in English so you can learn by reading the code.

---

## 🧠 The four pillars at a glance

| Pillar | What it is | Redis structure |
|--------|-----------|-----------------|
| **Memory** | The conversation log (what was said) | List (`RPUSH`/`LRANGE`/`LTRIM`) |
| **State** | The task's working data (what it's doing) | Hash (`HSET`/`HGETALL`) |
| **Checkpoints** | Snapshots so a run resumes after a crash | Append-only List |
| **Shared memory** | A blackboard many agents read/write | Hash + Pub/Sub + locks |

**Memory ≠ State.** Memory is the *conversation*; state is the *task's working data*.

---

## 🤖 The six agents (Project 5)

```
planner → researcher → retriever → tool_router → executor → reviewer
                                                     ▲            │
                                                     │  approved? │
                                               (revise) ◄─ no yes ─► END
```

| Agent | Job |
|-------|-----|
| **Planner** | Break the task into an ordered plan |
| **Researcher** | Gather background facts |
| **Retriever** | Pull relevant documents |
| **Tool Router** | Decide which tools to call |
| **Executor** | Run tools and assemble a draft |
| **Reviewer** | Approve, or loop back to revise (conditional edge) |

---

## 🚀 Quick start

### 1. Start Redis
```bash
cd project_multi_agent
docker compose up -d          # or: redis-server --daemonize yes
redis-cli ping                # → PONG
```

### 2. Run the four concepts
```bash
pip install redis
cd concepts
python 01_agent_memory.py       # remembers your name across turns
python 02_state_management.py   # planner & executor share state
python 03_checkpointing.py      # crashes, then resumes without repeating work
python 04_shared_memory.py      # blackboard + lock + pub/sub
```

### 3. Run the multi-agent system
```bash
cd project_multi_agent
pip install -r requirements.txt
python run_cli.py               # full run + crash/resume demo
```

Or as an API:
```bash
uvicorn main:app --reload
# open http://localhost:8000/docs
```

### 4. Watch it work
```bash
curl -X POST localhost:8000/run -H "Content-Type: application/json" \
     -d '{"task":"Explain how Redis powers AI agents"}'

curl localhost:8000/run/<run_id>/state    # the shared state
curl localhost:8000/run/<run_id>/board    # what each agent shared
curl localhost:8000/run/<run_id>/trace    # every checkpointed node
```

You'll see the **review loop** (executor → reviewer → executor → reviewer) and,
in `run_cli.py`, a **crash mid-run that resumes** from the last checkpoint
without repeating the earlier agents.

---

## 🔀 Mapping to real LangGraph

This project hand-builds the graph so the mechanics are visible. It maps
one-to-one onto real LangGraph:

| This project | Real LangGraph |
|--------------|----------------|
| node functions in `agents.py` | `graph.add_node(...)` |
| `LINEAR_NEXT` edges | `graph.add_edge(...)` |
| `_route_after_reviewer` | `graph.add_conditional_edges(...)` |
| `state.py` (Redis hash) | the typed `State` schema |
| `checkpointer.py` | `langgraph-checkpoint-redis` |

Install `langgraph` + `langgraph-checkpoint-redis` to swap in the real framework
once these ideas are second nature.

---

## 🔌 Using real Groq (optional)

By default the system uses deterministic **mock** agents (zero setup, zero cost).
To use real models:

```bash
cd project_multi_agent
cp .env.example .env
# edit .env and set:  GROQ_API_KEY=your_groq_key
```

No code changes — `config.py` detects the key and the same agents call Groq.

---

## ✅ Requirements
- Python 3.10+
- Redis (via Docker or local install)
- `pip install redis fastapi "uvicorn[standard]"` (and `groq` only for real models)

---

## ➡️ Next: Phase 7 — Production Redis

You've built agents that remember, coordinate, and survive crashes. Phase 7 is
about running them reliably at scale: **clustering, Sentinel, persistence
(RDB/AOF), monitoring, high availability, and disaster recovery.**
