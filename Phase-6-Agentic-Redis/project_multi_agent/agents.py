"""
============================================================================
 AGENTS - the six specialists, each one a node in the graph
============================================================================
Every agent is a function with the SAME shape:

    def agent(state: dict) -> dict:
        ...read from state...
        ...do work (mock LLM/tool, or real Groq if a key is set)...
        return {"field": new_value, ...}   # only the fields it changed

The graph (graph.py) calls each one in turn, merges the returned fields into
the shared state, posts progress to the blackboard, and checkpoints. Keeping
every agent the same shape is exactly how LangGraph nodes work.

THE PIPELINE
------------
    Planner -> Researcher -> Retriever -> ToolRouter -> Executor -> Reviewer
                                                             ^            |
                                                             |            v
                                                     (revise if not approved)
============================================================================
"""

import config
import shared_memory as bb


# ---------------------------------------------------------------------------
# Optional real-LLM helper. If GROQ_API_KEY is set we call Groq; otherwise
# every agent uses its deterministic mock logic so the whole system runs
# offline. Keeping this in one place means agents don't repeat the plumbing.
# ---------------------------------------------------------------------------
def _llm(prompt: str) -> str:
    if config.USE_REAL_GROQ:
        from groq import Groq

        client = Groq(api_key=config.GROQ_API_KEY)
        resp = client.chat.completions.create(
            model=config.LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        return resp.choices[0].message.content
    # Mock: echo a short deterministic response so demos are reproducible.
    return f"[mock-llm output for: {prompt[:60]}...]"


# ===========================================================================
# 1. PLANNER  - turn the task into an ordered plan
# ===========================================================================
def planner(state: dict) -> dict:
    task = state["task"]
    # A real planner asks the LLM to decompose the task. We mock a fixed plan.
    plan = [
        f"Gather background facts about: {task}",
        f"Retrieve supporting documents for: {task}",
        f"Run any tools needed for: {task}",
        f"Write and review the final answer",
    ]
    bb.post(state["run_id"], "Planner", {"plan_steps": len(plan)})
    print(f"      [Planner]    created a {len(plan)}-step plan")
    return {"plan": plan}


# ===========================================================================
# 2. RESEARCHER  - gather background knowledge/facts
# ===========================================================================
def researcher(state: dict) -> dict:
    task = state["task"]
    findings = [
        f"Fact 1 about {task}",
        f"Fact 2 about {task}",
    ]
    bb.post(state["run_id"], "Researcher", {"facts": findings})
    print(f"      [Researcher] gathered {len(findings)} facts")
    return {"research": findings}


# ===========================================================================
# 3. RETRIEVER  - pull relevant documents (would query a vector DB)
# ===========================================================================
def retriever(state: dict) -> dict:
    task = state["task"]
    docs = [
        {"id": "doc_A", "text": f"Document A relevant to {task}"},
        {"id": "doc_B", "text": f"Document B relevant to {task}"},
    ]
    bb.post(state["run_id"], "Retriever", {"doc_ids": [d["id"] for d in docs]})
    print(f"      [Retriever]  retrieved {len(docs)} documents")
    return {"documents": docs}


# ===========================================================================
# 4. TOOL ROUTER  - decide which tools to call based on the task
# ===========================================================================
# In a real agent this is where the LLM chooses tools (function calling).
AVAILABLE_TOOLS = {
    "calculator": lambda: "calc_result=42",
    "web_search": lambda: "search_result=top hit",
}


def tool_router(state: dict) -> dict:
    task = state["task"].lower()
    # Simple routing rules for the demo (an LLM would decide this).
    chosen = []
    if any(w in task for w in ["calculate", "sum", "math", "number"]):
        chosen.append("calculator")
    if any(w in task for w in ["latest", "news", "current", "today", "search"]):
        chosen.append("web_search")
    if not chosen:
        chosen = ["web_search"]  # sensible default
    bb.post(state["run_id"], "ToolRouter", {"tools": chosen})
    print(f"      [ToolRouter] selected tools: {chosen}")
    return {"tool_plan": chosen}


# ===========================================================================
# 5. EXECUTOR  - run the chosen tools and assemble a draft answer
# ===========================================================================
def executor(state: dict) -> dict:
    run_id = state["run_id"]
    # --- Run each selected tool (guarded by a lock so concurrent executors
    #     for the same run can't produce duplicate results) ---
    results = []
    token = bb.acquire_lock(f"exec:{run_id}")
    try:
        for tool in state.get("tool_plan", []):
            fn = AVAILABLE_TOOLS.get(tool)
            results.append({"tool": tool, "output": fn() if fn else "unknown tool"})
    finally:
        if token:
            bb.release_lock(f"exec:{run_id}", token)

    # --- Assemble a draft from everything gathered so far ---
    draft = _llm(
        "Write an answer to '{task}' using facts {facts}, docs {docs}, "
        "and tool results {tools}.".format(
            task=state["task"],
            facts=state.get("research", []),
            docs=[d["id"] for d in state.get("documents", [])],
            tools=results,
        )
    )
    bb.post(run_id, "Executor", {"tools_run": len(results)})
    print(f"      [Executor]   ran {len(results)} tool(s) and wrote a draft")
    return {"tool_results": results, "draft": draft}


# ===========================================================================
# 6. REVIEWER  - approve the draft, or request a revision (creates a loop)
# ===========================================================================
def reviewer(state: dict) -> dict:
    revision = state.get("revision", 0)
    # Mock review logic: reject the first draft once to demonstrate the loop,
    # then approve. A real reviewer would use an LLM to grade the draft.
    approved = revision >= 1
    verdict = {
        "approved": approved,
        "notes": "Looks good." if approved else "Needs more detail; revise.",
    }
    bb.post(state["run_id"], "Reviewer", verdict)
    print(f"      [Reviewer]   verdict: "
          f"{'APPROVED' if approved else 'REVISE'} (revision {revision})")

    changes = {"review": verdict}
    if approved:
        changes["result"] = state.get("draft", "")   # promote draft to result
    else:
        changes["revision"] = revision + 1            # trigger another loop
    return changes
