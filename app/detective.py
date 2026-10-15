"""Part 2, the agent part: Sergeant Wilkes, a detective's assistant with tools."""

import json
import hashlib
from pathlib import Path

from .evidence import EvidenceIndex

# Who did it, hashed so that reading the code doesn't spoil the mystery
_CULPRIT_HASH = "e69500e67ba4c7c11ef0f68475481ab73ac14b60c0362798cf9e38876a7ce536"
_TITLES = {"dr", "doctor", "lady", "lord", "colonel", "col", "mr", "mrs", "miss", "the", "butler"}

BRIEFING = (
    "Blackwood Manor, Sunday 15 November 1931, 08:00. Lord Edmund Blackwood was found dead in his "
    "library last night. The lane was flooded, so the killer is still in the house. You have the case "
    "files, the suspects' accounts of their evening, and one accusation. Make it count."
)

SYSTEM_PROMPT = """You are Sergeant Wilkes, assisting the inspector (the user) on the Blackwood Manor murder case.
Help the inspector by digging through the evidence with your tools. Look things up instead of guessing,
and name the case file (doc_id) every fact comes from. Point out contradictions between statements.
You do not know who the murderer is. Never call `accuse` unless the inspector explicitly tells you to
accuse someone; there is only one accusation per case. Keep answers short, and stay in character."""


class CaseFile:
    """All evidence loaded from one case folder.

    Bundles the search index over the case's Markdown files with the
    suspects' timelines from ``suspects.json``, so tools only need one
    object to reach everything.

    Attributes:
        index: Search index over every ``*.md`` file in the case folder.
        suspects: Suspect data keyed by suspect id (e.g. ``"clara"``). Each
            value has a ``"name"``, a ``"role"`` and a ``"timeline"`` list of
            ``{"from", "to", "where", "witnesses"}`` entries.
    """

    def __init__(self, index: EvidenceIndex, suspects: dict):
        self.index = index
        self.suspects = suspects  # see case_files/suspects.json

    @classmethod
    def load(cls, case_dir: Path) -> "CaseFile":
        """Loads a case file from a folder on disk.

        Args:
            case_dir: Folder containing the case's ``*.md`` documents and a
                ``suspects.json`` file.

        Returns:
            A CaseFile with the search index built and the suspects loaded.

        Raises:
            FileNotFoundError: If ``suspects.json`` is missing or the folder
                contains no Markdown files.
            json.JSONDecodeError: If ``suspects.json`` is not valid JSON.
        """
        suspects = json.loads((Path(case_dir) / "suspects.json").read_text(encoding="utf-8"))
        return cls(EvidenceIndex.from_dir(case_dir), suspects)

    def find_suspect(self, name: str) -> str:
        """Resolves a loosely written name to exactly one suspect id.

        Matching ignores case, surrounding punctuation and titles such as
        "Dr." or "Miss". A suspect matches if any remaining word of
        ``name`` appears in their full name, so "Miss Clara", "clara" and
        "Clara Blackwood" all resolve to ``"clara"``.

        Args:
            name: The name as written by the user or the model.

        Returns:
            The id of the matching suspect, e.g. ``"clara"``.

        Raises:
            ValueError: If the name matches no suspect, or more than one
                (for example just "Blackwood"). The message lists all
                suspects so the model can retry with a better name.
        """
        words = {w.strip(".,").lower() for w in name.split()} - _TITLES
        matches = [sid for sid, s in self.suspects.items()
                   if words & ({w.strip(".,").lower() for w in s["name"].split()} - _TITLES)]
        if len(matches) != 1:
            known = ", ".join(s["name"] for s in self.suspects.values())
            problem = "matches more than one suspect" if matches else "is not a suspect"
            raise ValueError(f"{name!r} {problem}. The suspects are: {known}")
        return matches[0]


def is_culprit(suspect_id: str) -> bool:
    """Checks whether a suspect is the murderer, without revealing who it is.

    The answer is stored only as an SHA-256 hash, so reading the source
    doesn't spoil the mystery. The id is salted with the prefix
    ``"blackwood:"`` before hashing, which stops a precomputed table of
    hashed names from looking it up directly.

    Args:
        suspect_id: A suspect id from ``suspects.json``, e.g. ``"clara"``
            or ``"ashby"``. Use ``CaseFile.find_suspect`` to turn a written
            name into an id first.

    Returns:
        True if ``suspect_id`` is the culprit, False otherwise. An unknown
        id simply returns False.
    """
    return hashlib.sha256(f"blackwood:{suspect_id}".encode()).hexdigest() == _CULPRIT_HASH


# ---------------------------------------------------------------------------
# Step 2: Tools
# ---------------------------------------------------------------------------

def search_evidence(inv: "Investigation", query: str) -> str:
    """Searches all case files and returns the best-matching passages.

    This is a RAG tool: the model calls it with keywords and gets back
    the top passages from the investigation's evidence index, each tagged
    with its doc_id so the model can cite it or read the whole file.

    Args:
        inv: The investigation this tool runs in. Only its case file is used.
        query: Keywords to search for, e.g. ``"brandy decanter"``.

    Returns:
        One line per hit, the best first, formatted as
        ``"[doc_id] Title: snippet"``.

    Raises:
        ValueError: If no case file matches the query. The agent loop
            returns this to the model as an error result, so it can retry
            with different words.
    """
    top_k = inv.case_file.index.search(query)
    if len(top_k) == 0:
        raise ValueError(f"No case files found for query {query}.")
    return "\n".join([f"[{r["doc_id"]}] {r["title"]}: {r["snippet"]}" for r in top_k])


def read_document(inv: "Investigation", doc_id: str) -> str:
    """Returns the full text of one case file.

    Lets the model read a whole document after a search hit pointed to it.

    Args:
        inv: The investigation this tool runs in.
        doc_id: The document's id, e.g. ``"coroner-report"``.

    Returns:
        The complete Markdown text of the document.

    Raises:
        ValueError: If no document has this id. The message lists all
            available ids so the model can retry.
    """
    doc = inv.case_file.index.get(doc_id)
    if doc is None:
        documents = ", ".join(inv.case_file.index.document_dict.keys())
        raise ValueError(f"No document with doc id {doc_id} found. Available doc ids: {documents}")
    return doc["text"]


def list_suspects(inv: "Investigation") -> str:
    """Lists everyone who could have committed the murder.

    Args:
        inv: The investigation this tool runs in.

    Returns:
        One line per suspect, formatted as ``"Name: role"``.
    """
    return "\n".join(f"{s["name"]}: {s["role"]}" for s in inv.case_file.suspects.values())


def check_alibi(inv: "Investigation", suspect: str, time: str) -> str:
    """Looks up where a suspect claims to have been at a given time.

    Searches the suspect's timeline for the entry covering ``time`` and
    reports the location and any witnesses who confirm it.

    Args:
        inv: The investigation this tool runs in.
        suspect: The suspect's name as written, e.g. ``"Miss Clara"``.
        time: A 24-hour time on the night of the murder, as ``"HH:MM"``.

    Returns:
        A sentence with the claimed location and its witnesses, or a note
        that the suspect has no account of that time.

    Raises:
        ValueError: If ``time`` is not a valid ``HH:MM`` time, or if
            ``suspect`` doesn't match exactly one suspect.
    """
    hours, _, minutes = time.partition(":")
    if not (hours.isdigit() and minutes.isdigit() and int(hours) < 24 and int(minutes) < 60 and len(minutes) == 2):
        raise ValueError(f"Time must have format 'HH:MM', e.g. '22:30', got {time!r}")
    time = f"{int(hours):02d}:{minutes}"

    candidate_suspect = inv.case_file.find_suspect(suspect)
    candidate_suspect_dict = inv.case_file.suspects[candidate_suspect]

    out = f"Suspect: {candidate_suspect_dict["name"]} "
    for t in candidate_suspect_dict["timeline"]:
        if t["from"] <= time <= t["to"]:
            out += f"claims to have been at/in {t["where"]}."
            witnesses = t["witnesses"]
            if len(witnesses) == 0:
                out += "There are no witnesses to this claim."
            else:
                witnesses = ", ".join(witnesses)
                out += f"This claim is confirmed by {witnesses}"
            break
    else:
        out += f"does not have an alibi for the time {time}."
    return out


def accuse(inv: "Investigation", suspect: str, reasoning: str) -> str:
    """Formally accuses a suspect, which ends the case either way.

    This is a risky tool: the agent loop only runs it after the inspector
    approves. It sets ``inv.accused`` and ``inv.verdict`` (``"solved"`` or
    ``"failed"``), and only one accusation is allowed per investigation.

    Args:
        inv: The investigation this tool runs in. It is modified.
        suspect: The accused suspect's name as written.
        reasoning: The model's short justification. It is not used to
            decide the outcome.

    Returns:
        A short dramatic ending describing whether the case was solved.

    Raises:
        ValueError: If an accusation was already made, or if ``suspect``
            doesn't match exactly one suspect.
    """
    if inv.accused is not None:
        raise ValueError("There can only be a single accusation per case file.")
    candidate_suspect = inv.case_file.find_suspect(suspect)
    inv.accused = inv.case_file.suspects[candidate_suspect]["name"]
    if is_culprit(candidate_suspect):
        inv.verdict = "solved"
        return f"""The suspect {inv.accused} could no longer hide it.
            They tried to sneak out the back into the gardens, but to no avail.
            Their time has come and Blackwood Manor is once again free of evil energies. {reasoning}
            """
    inv.verdict = "failed"
    return f"""Even though the detectives worked with in a sheer perfect manner, the true suspect remains hidden.
        {inv.accused} has remained behind bars for weeks now, always claiming innocence. And they were right!
        """


TOOLS = [
    {
        "name": "search_evidence",
        "description": "Search all case files (statements, coroner's report, police search, will, floor plan) "
                       "and return the 3 most relevant paragraphs with their doc_id.",
        "input_schema": {"type": "object", "properties": {
            "query": {"type": "string", "description": "Keywords, e.g. 'brandy decanter' or 'grey tweed jacket'."}},
                         "required": ["query"]},
    },
    {
        "name": "read_document",
        "description": "Read the content of one case file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "doc_id": {
                    "type": "string",
                    "description": "The document identifier, e.g. 'butler-statement.md'."
                }
            },
            "required": ["doc_id"],
        }
    },
    {
        "name": "list_suspects",
        "description": "Retrieve a list of all known suspects, one per line.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        }
    },
    {
        "name": "check_alibi",
        "description": "Check the alibi of a suspect for a given time.",
        "input_schema": {
            "type": "object",
            "properties": {
                "suspect": {
                    "type": "string",
                    "description": "The suspect's name, e.g. 'Clara Blackwood'."
                },
                "time": {
                    "type": "string",
                    "description": "The time for which to check the alibi in the format 'HH:MM', e.g. '22:20'."
                }
            },
            "required": ["suspect", "time"],
        }
    },
    {
        "name": "accuse",
        "description": "Finish the story by accusing a suspect.",
        "input_schema": {
            "type": "object",
            "properties": {
                "suspect": {
                    "type": "string",
                    "description": "The suspect's name, e.g. 'Clara Blackwood'."
                },
                "reasoning": {
                    "type": "string",
                    "description": "The reasoning behind the accusation."
                }
            },
            "required": ["suspect", "reasoning"],
        }
    }
]

TOOL_FUNCTIONS = {
    "search_evidence": search_evidence,
    "read_document": read_document,
    "list_suspects": list_suspects,
    "check_alibi": check_alibi,
    "accuse": accuse,
}

RISKY_TOOLS = {"accuse"}


# ---------------------------------------------------------------------------
# Step 3: The investigation, an agent loop that can pause for approval
# ---------------------------------------------------------------------------

class InvestigationError(Exception):
    """Raised when an action isn't allowed in the investigation's current state."""


class Investigation:
    """One player's investigation: the conversation with the agent and its state.

    Runs the agent loop, which can pause when the model wants a risky tool
    (``accuse``) and resume once the inspector decides. Everything that must
    survive between two API requests lives on this object.

    Attributes:
        case_file: The evidence the tools work on.
        max_turns: Maximum model calls per ``ask``/``decide`` call.
        messages: The full conversation in Claude API message format.
        pending: ``{"tool": ..., "input": ...}`` while a risky tool call
            awaits approval, otherwise None.
        verdict: None while the case is open, then ``"solved"`` or ``"failed"``.
        accused: Full name of the accused suspect, or None.
    """

    def __init__(self, case_file: CaseFile, max_turns: int = 8):
        self.case_file = case_file
        self.max_turns = max_turns
        self.messages: list[dict] = []
        self.pending: dict | None = None  # {"tool": ..., "input": ...} while waiting for approval
        self.verdict: str | None = None  # None, "solved" or "failed"
        self.accused: str | None = None

    @property
    def status(self) -> str:
        """The investigation's state, derived from ``verdict`` and ``pending``.

        Returns:
            ``"solved"`` or ``"failed"`` once an accusation was made,
            ``"awaiting_approval"`` while a tool call is pending, and
            ``"investigating"`` otherwise.
        """
        if self.verdict is not None:
            return self.verdict
        return "awaiting_approval" if self.pending else "investigating"

    def run_tool(self, name: str, tool_input: dict) -> tuple[str, bool]:
        """Runs one tool and turns any failure into an error result.

        Args:
            name: The tool name from the model's ``tool_use`` block.
            tool_input: The tool's keyword arguments.

        Returns:
            A ``(text, is_error)`` tuple. Unknown tools and exceptions raised
            by the tool give ``is_error=True`` with the error as text, so the
            model can correct itself. This method never raises.
        """
        if name not in TOOL_FUNCTIONS:
            return f"Error: Unknown tool name {name}", True
        try:
            return TOOL_FUNCTIONS[name](self, **tool_input), False
        except Exception as e:
            return f"Error: {e}", True

    def _handle_tool_use(self, content: list[dict], approved: bool, log: list[dict]):
        """Runs the tool calls of one assistant message and collects the results.

        Args:
            content: The content blocks of an assistant message. Blocks that
                aren't ``tool_use`` are skipped.
            approved: Whether risky tools may run. If False, they aren't
                executed and get an error result instead.
            log: List to append a ``{"name", "input", "is_error"}`` entry to
                for every tool call. It is modified.

        Returns:
            A user message holding one ``tool_result`` per ``tool_use`` block.
        """
        tool_results = []
        for block in content:
            if block["type"] != "tool_use":
                continue
            if block["name"] in RISKY_TOOLS and not approved:
                text, is_error = "Error: Tool execution not approved", True
            else:
                text, is_error = self.run_tool(block["name"], block["input"])
            log.append({"name": block["name"], "input": block["input"], "is_error": is_error})
            tool_results.append(
                {"type": "tool_result", "tool_use_id": block["id"], "content": text, "is_error": is_error})
        return {"role": "user", "content": tool_results}

    def _agent_loop(self, model, log: list[dict]) -> dict:
        """Calls the model and runs its tools until it answers or must pause.

        Stops when the model gives a final answer, when it asks for a risky
        tool (sets ``self.pending``), or after ``max_turns`` model calls.

        Args:
            model: Callable ``(system, messages, tools) -> response``.
            log: Tool-call log for this turn, extended in place.

        Returns:
            The turn dict ``{"status", "reply", "tool_calls", "pending"}``.
            ``reply`` is None when paused for approval.
        """
        reply = "The model used all turns before finishing the assignment."
        for _ in range(self.max_turns):
            response = model(SYSTEM_PROMPT, self.messages, TOOLS)
            self.messages.append({"role": "assistant", "content": response["content"]})
            if response["stop_reason"] != "tool_use":
                reply = "\n".join(content["text"] for content in response["content"] if content["type"] == "text")
                break
            risky_tool_calls = [block for block in response["content"]
                                if block["type"] == "tool_use" and block["name"] in RISKY_TOOLS]
            if len(risky_tool_calls) > 0:
                self.pending = {"tool": risky_tool_calls[0]["name"], "input": risky_tool_calls[0]["input"]}
                reply = None
                break
            self.messages.append(self._handle_tool_use(response["content"], False, log))
        return {"status": self.status, "reply": reply, "tool_calls": log, "pending": self.pending}

    def ask(self, text: str, model) -> dict:
        """Sends the inspector's message to the agent and runs the loop.

        If the conversation already ends on a user message (after hitting
        ``max_turns`` or a failed model call), the text is merged into it so
        user and assistant turns keep alternating.

        Args:
            text: The inspector's message.
            model: Callable ``(system, messages, tools) -> response``.

        Returns:
            The turn dict ``{"status", "reply", "tool_calls", "pending"}``.

        Raises:
            InvestigationError: If the status isn't ``"investigating"``.
        """
        if self.status != "investigating":
            raise InvestigationError(f"Case status is {self.status}, can not ask questions.")
        last = self.messages[-1] if self.messages else None
        if last and last["role"] == "user":
            # Conversation is supposed to alternate user -> assistant -> user -> ...
            # Keep history clean by merging user turns
            # This is an edge case that might happen on network errors or when max_turns is hit
            if isinstance(last["content"], str):
                last["content"] = [{"type": "text", "text": last["content"]}]
            last["content"].append({"type": "text", "text": text})
        else:
            self.messages.append({"role": "user", "content": text})
        return self._agent_loop(model, [])

    def decide(self, approved: bool, model) -> dict:
        """Resolves the pending tool call and resumes the loop.

        Builds the tool results for the paused assistant message (the last
        message), running the risky tool only if approved, then continues
        the agent loop.

        Args:
            approved: True to run the pending tool, False to decline it.
            model: Callable ``(system, messages, tools) -> response``.

        Returns:
            The turn dict ``{"status", "reply", "tool_calls", "pending"}``.

        Raises:
            InvestigationError: If no tool call is pending.
        """
        if self.pending is None:
            raise InvestigationError("There is currently no tool call pending.")
        self.pending = None
        log = []
        self.messages.append(self._handle_tool_use(self.messages[-1]["content"], approved, log))
        return self._agent_loop(model, log)
