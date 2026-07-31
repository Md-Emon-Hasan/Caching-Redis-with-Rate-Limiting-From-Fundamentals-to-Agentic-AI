"""
============================================================================
 PHASE 6 - CONCEPT 1: AGENT MEMORY (Short-Term / Conversation Memory)
============================================================================

THE CORE PROBLEM
----------------
An LLM is STATELESS. Every API call is a blank slate - the model does not
remember your previous message. If a user says:

    Turn 1: "My name is Rahim."
    Turn 2: "What is my name?"

...the model has no idea, unless YOU send the earlier turns back to it.
So an "agent with memory" is really an agent whose framework stores the
conversation somewhere and replays it into each new prompt.

Redis is perfect for this: fast, in-memory, and it has a LIST data type
that behaves exactly like a growing chat log.

THE IDEA
--------
    User message
        |
        v
    append to Redis LIST  (conversation:{id})
        |
        v
    read last N turns  ->  build prompt  ->  LLM  ->  reply
        |
        v
    append reply to the SAME list

WHY A REDIS LIST?
-----------------
A conversation is an ORDERED sequence of turns. Redis lists give us:
    RPUSH  -> append a turn to the end        (O(1))
    LRANGE -> read a slice (e.g. last 10)     (fast)
    LTRIM  -> keep only the most recent N     (windowing)
    EXPIRE -> auto-forget idle conversations  (TTL)

WINDOWING (why we don't keep everything)
----------------------------------------
LLMs have a limited context window, and long histories cost more tokens.
So we keep a sliding WINDOW of the most recent turns (e.g. last 20) and,
optionally, a running SUMMARY of everything older. This concept file shows
the windowing pattern; the summary idea is explained in comments.
============================================================================
"""

import json
import time

import redis


r = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)


# ---------------------------------------------------------------------------
# 1. KEYS
# ---------------------------------------------------------------------------
def _conversation_key(conversation_id: str) -> str:
    # One list per conversation. Namespaced with "conv:" so it never clashes
    # with other data in Redis.
    return f"conv:{conversation_id}:messages"


# ---------------------------------------------------------------------------
# 2. ADD A MESSAGE TO MEMORY
# ---------------------------------------------------------------------------
def add_message(conversation_id: str, role: str, content: str,
                max_turns: int = 20, ttl_seconds: int = 3600) -> None:
    """
    Append one message (a "turn") to the conversation history.

    role     : "user" or "assistant" (or "system"/"tool").
    max_turns: keep only the most recent N messages (the sliding window).
    ttl      : if the conversation is idle for this long, forget it entirely.
    """
    key = _conversation_key(conversation_id)

    # Each turn is a small JSON object. We store it as a JSON string because
    # Redis list elements are strings.
    turn = json.dumps({"role": role, "content": content, "ts": time.time()})

    # RPUSH appends to the END of the list (newest at the tail).
    r.rpush(key, turn)

    # LTRIM keeps only the last `max_turns` elements. Index -max_turns..-1
    # means "from N-from-the-end up to the very end". This is the sliding
    # window that stops the history from growing forever.
    r.ltrim(key, -max_turns, -1)

    # Refresh the TTL on every message so an ACTIVE conversation never
    # expires, but an abandoned one auto-cleans after `ttl_seconds` of silence.
    r.expire(key, ttl_seconds)


# ---------------------------------------------------------------------------
# 3. READ MEMORY (to build the next prompt)
# ---------------------------------------------------------------------------
def get_history(conversation_id: str, last_n: int | None = None) -> list[dict]:
    """
    Return the conversation as a list of {role, content} dicts, oldest first.
    last_n : only the most recent N turns (defaults to the whole window).
    """
    key = _conversation_key(conversation_id)

    if last_n is None:
        # LRANGE 0 -1 reads the ENTIRE list.
        raw = r.lrange(key, 0, -1)
    else:
        # -last_n .. -1 reads only the last N elements.
        raw = r.lrange(key, -last_n, -1)

    return [json.loads(item) for item in raw]


# ---------------------------------------------------------------------------
# 4. A TINY "AGENT" THAT USES MEMORY
# ---------------------------------------------------------------------------
def agent_reply(conversation_id: str, user_message: str) -> str:
    """
    A minimal agent turn:
      1. store the user's message,
      2. read the recent history,
      3. build a prompt from it (here we mock the LLM),
      4. store + return the reply.
    """
    # 1. Remember what the user just said.
    add_message(conversation_id, "user", user_message)

    # 2. Load recent context. THIS is the "memory" the LLM would otherwise lack.
    history = get_history(conversation_id, last_n=10)

    # 3. Mock "LLM": we just demonstrate that the model now SEES prior turns.
    #    In a real agent you'd send `history` to the LLM as the messages array.
    remembered_name = None
    for turn in history:
        if turn["role"] == "user" and "my name is" in turn["content"].lower():
            remembered_name = turn["content"].lower().split("my name is")[-1].strip(" .")

    if "what is my name" in user_message.lower():
        reply = (f"Your name is {remembered_name.title()}." if remembered_name
                 else "I don't know your name yet.")
    else:
        reply = f"(noted: '{user_message}')"

    # 4. Remember what the agent replied, so future turns have full context.
    add_message(conversation_id, "assistant", reply)
    return reply


# ---------------------------------------------------------------------------
# NOTE ON SUMMARIZATION (the next level up)
# ---------------------------------------------------------------------------
# For very long chats, instead of dropping old turns you SUMMARIZE them:
#   - Keep the last N turns verbatim (fast, exact).
#   - Periodically ask the LLM to compress older turns into a short summary
#     and store that summary in a separate Redis key (e.g. conv:{id}:summary).
#   - Build the prompt as:  [summary] + [last N verbatim turns].
# This keeps long-term context without blowing up the token count.


# ---------------------------------------------------------------------------
# DEMO  ->  run:  python 01_agent_memory.py
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    conv = "user-rahim-001"
    r.delete(_conversation_key(conv))  # start fresh for the demo

    print("USER : My name is Rahim.")
    print("AGENT:", agent_reply(conv, "My name is Rahim."))

    print("\nUSER : I love Redis.")
    print("AGENT:", agent_reply(conv, "I love Redis."))

    print("\nUSER : What is my name?")
    print("AGENT:", agent_reply(conv, "What is my name?"))
    #        ^ The agent answers correctly ONLY because memory was stored in
    #          Redis and replayed - the LLM itself is stateless.

    print("\n--- Full stored history in Redis ---")
    for turn in get_history(conv):
        print(f"  [{turn['role']:9}] {turn['content']}")
