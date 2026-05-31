"""
Context builder — assembles the context block injected into every LLM prompt.

Design principles (updated):
  - Working memory  : only the CURRENT session's turns. No cross-session history.
  - Semantic memory : NOT injected. Cross-session retrieval caused the model to
                      assert things from old sessions as if they were current facts.
  - Structured data : goals and decisions are injected with explicit source labels
                      so the model can cite them correctly.
  - Brain State     : always included — it's live data, not remembered inference.

Each context section is labelled with its source so the system prompt's
citation rule ("cite it or don't say it") is actionable.
"""
from intelligence import brain_state as bs
from memory import working, structured

_MAX_CHARS = 2000


def build(query: str, session_id: str | None = None) -> str:
    parts: list[str] = []

    # 1. Brain State — live sensor data, always trustworthy
    state = bs.get()
    parts.append(
        f"[LIVE STATE — source: brain_state sensor]\n"
        f"Focus:{state.get('focus')}/10  "
        f"Energy:{state.get('energy')}/10  "
        f"Stress:{state.get('stress')}/10  "
        f"Activity:{state.get('current_activity')}  "
        f"Location:{state.get('location')}"
    )

    # 2. Working memory — THIS session only, verbatim turns
    sid = session_id or working.current_session()
    ctx = working.get_context_block(sid, max_chars=900)
    if ctx:
        parts.append(
            f"[CONVERSATION SO FAR — source: current session {sid}]\n{ctx}"
        )

    # 3. Active goals — user-set, cite as "your stated goals"
    try:
        goals = structured.get_active_goals()
        if goals:
            lines = [f"  • {g['description']}" for g in goals[:3]]
            parts.append(
                "[YOUR STATED GOALS — source: goals you set]\n" + "\n".join(lines)
            )
    except Exception:
        pass

    # 4. Recent decisions — last 3 days, cite as "recent decisions"
    try:
        decisions = structured.get_decisions(days=3)
        if decisions:
            lines = [f"  • {d['description']}" for d in decisions[:3]]
            parts.append(
                "[RECENT DECISIONS — source: decisions logged in last 3 days]\n"
                + "\n".join(lines)
            )
    except Exception:
        pass

    # 5. Approved dream patterns — high-quality synthetic insights
    try:
        from intelligence.unified_memory import search_memory
        dream_hits = search_memory(query, n_each=1).get("intel_dreams", [])
        if dream_hits:
            lines = [f"  • {h['text'][:150]}" for h in dream_hits[:2]]
            parts.append(
                "[LEARNED PATTERN — source: approved dream session]\n"
                + "\n".join(lines)
            )
    except Exception:
        pass

    block = "\n\n".join(parts)

    if len(block) > _MAX_CHARS:
        head = block[:700]
        tail = block[-(_MAX_CHARS - 700):]
        block = head + "\n...[truncated]...\n" + tail

    return block


# Core identity — injected into every chat
_BASE_IDENTITY = """
You are PARV-AI, Parv's personal AI. Your job is to be useful, not agreeable.

TONE:
- Direct and concise. Say the thing. No preamble, no filler, no "great question!".
- Never flatter or validate just to be positive. If something is wrong, say so plainly.
- No motivational language. No "you've got this" or "amazing". Skip it entirely.
- Don't take sides on opinion questions. Present the tradeoffs and let Parv decide.
- Match the register: technical when the question is technical, brief when the question is brief.

BEHAVIOUR:
- Answer what was asked. Don't pad with tangents or unsolicited advice.
- If you don't know something, say "I don't know" — not a workaround, not a hedge.
- If a request is ambiguous, ask one specific clarifying question instead of guessing.
- Never repeat back what the user just said as a way of starting a response.
- No sign-offs. Don't end with "Let me know if you need anything!".
""".strip()

# Memory rules — injected after identity, before context
_MEMORY_POLICY = """
MEMORY RULES:
1. Only use what's in this conversation. Never assume prior context not shown here.
2. If you reference something Parv said, cite it: "you mentioned [this session]". Can't cite it? Don't assert it.
3. "I don't have that from our current conversation" is always the right answer when you're missing information.
4. Label inferences explicitly — "my inference:" — before stating them.
""".strip()


def build_system_prompt(
    query: str,
    session_id: str | None = None,
    base_system: str = _BASE_IDENTITY,
) -> str:
    ctx = build(query, session_id)
    parts = [_BASE_IDENTITY, _MEMORY_POLICY]
    if ctx:
        parts.append(ctx)
    return "\n\n".join(parts)
