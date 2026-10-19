"""The two "models" the detective can use. Provided, no edits needed.

Both take (system, messages, tools) and return the next assistant message:

    {"stop_reason": "tool_use" | "end_turn" | ...,
     "content": [{"type": "text", "text": "..."},
                 {"type": "tool_use", "id": "toolu_...", "name": "...", "input": {...}}]}

  call_model  asks Claude (needs ANTHROPIC_API_KEY).
  fake_model  a tiny command parser that pretends to be a model, so the whole
              service runs without an API key. Send it messages like:
                  search brandy decanter
                  read coroner-report
                  suspects
                  alibi Clara 22:30
                  accuse Colonel Ashby
              Anything else is treated as a search.
"""
import os
import re
import uuid
import logging

logger = logging.getLogger(__name__)

MODEL = "claude-opus-5-5"  # or "claude-sonnet-5-5" for a cheaper model


def has_api_key() -> bool:
    """Check whether the env-variable ANTHROPIC_API_KEY key is set.

    Returns:
        True if the API key has been set, else False.
    """
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def call_model(system: str, messages: list[dict], tools: list[dict], max_tokens: int = 16000) -> dict:
    """Send the whole conversation plus the tool list to Claude, return its next message."""
    if not has_api_key():
        raise RuntimeError("ANTHROPIC_API_KEY is not set")

    import anthropic

    client = anthropic.Anthropic()
    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=messages,
        tools=tools,
        output_config={"effort": "low"},
        # If Claude's safety filters ever decline a request, retry it on a
        # fallback model automatically instead of returning nothing.
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    if response.stop_reason == "refusal":
        return {"stop_reason": "refusal", "content": [{"type": "text", "text": "[Claude declined this request]"}]}
    return {
        "stop_reason": response.stop_reason,
        "content": [block.model_dump(exclude_none=True) for block in response.content],
    }


FAKE_HELP = """I'm the fake model, so I only understand commands:
  search <words>        search the case files
  read <doc_id>         read one whole case file, e.g. read coroner-report
  suspects              list the suspects
  alibi <name> <HH:MM>  where was someone at that time?
  accuse <name>         name the murderer (asks for approval first)
Set DETECTIVE_MODEL=claude and ANTHROPIC_API_KEY to talk to a real detective."""


def _tool_use(name: str, **tool_input) -> dict:
    block = {"type": "tool_use", "id": f"toolu_{uuid.uuid4().hex[:12]}", "name": name, "input": tool_input}
    return {"stop_reason": "tool_use", "content": [block]}


def _say(text: str) -> dict:
    return {"stop_reason": "end_turn", "content": [{"type": "text", "text": text}]}


def fake_model(system: str, messages: list[dict], tools: list[dict]) -> dict:
    """Send a fake request."""
    logger.info("Sending request. System prompt length: %s. Tool count: %s.", len(system), len(tools))
    last = messages[-1]["content"]
    if isinstance(last, list) and any(b.get("type") == "tool_result" for b in last):
        # A tool just ran: "answer" by passing its output straight back.
        return _say("\n\n".join(b["content"] for b in last if b.get("type") == "tool_result"))

    text = last if isinstance(last, str) else " ".join(b.get("text", "") for b in last if b.get("type") == "text")
    command, _, rest = text.strip().partition(" ")
    command, rest = command.lower(), rest.strip()
    if command == "search" and rest:
        return _tool_use("search_evidence", query=rest)
    if command == "read" and rest:
        return _tool_use("read_document", doc_id=rest)
    if command == "suspects":
        return _tool_use("list_suspects")
    if command == "alibi":
        match = re.match(r"(.+?)\s+(\d{1,2}:\d{2})$", rest)
        if not match:
            return _say("Usage: alibi <name> <HH:MM>, for example: alibi Clara 22:30")
        return _tool_use("check_alibi", suspect=match.group(1), time=match.group(2))
    if command == "accuse" and rest:
        return _tool_use("accuse", suspect=rest, reasoning="The inspector's hunch.")
    if command in {"help", "?", ""}:
        return _say(FAKE_HELP)
    return _tool_use("search_evidence", query=text)
