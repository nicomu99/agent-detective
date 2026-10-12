"""Part 2, the agent part: Sergeant Wilkes, a detective's assistant with tools."""

import json
import hashlib
from datetime import datetime
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
    """Provided: everything loaded from the case folder, the search index plus the suspects' timelines."""

    def __init__(self, index: EvidenceIndex, suspects: dict):
        self.index = index
        self.suspects = suspects  # see case_files/suspects.json

    @classmethod
    def load(cls, case_dir: Path) -> "CaseFile":
        suspects = json.loads((Path(case_dir) / "suspects.json").read_text(encoding="utf-8"))
        return cls(EvidenceIndex.from_dir(case_dir), suspects)

    def find_suspect(self, name: str) -> str:
        """Return the suspect id ("clara") for a name like "Miss Clara". Raises ValueError otherwise."""
        words = {w.strip(".,").lower() for w in name.split()} - _TITLES
        matches = [sid for sid, s in self.suspects.items()
                   if words & ({w.strip(".,").lower() for w in s["name"].split()} - _TITLES)]
        if len(matches) != 1:
            known = ", ".join(s["name"] for s in self.suspects.values())
            problem = "matches more than one suspect" if matches else "is not a suspect"
            raise ValueError(f"{name!r} {problem}. The suspects are: {known}")
        return matches[0]


def is_culprit(suspect_id: str) -> bool:
    """Provided: True if this suspect id ("clara", "finch", ...) is the murderer."""
    return hashlib.sha256(f"blackwood:{suspect_id}".encode()).hexdigest() == _CULPRIT_HASH


# ---------------------------------------------------------------------------
# Step 2: Tools
# Each tool gets the Investigation it runs in as its first argument, so it can
# reach inv.case_file (and, for accuse, set inv.verdict and inv.accused).
# Tools return a string for the model; on bad input they raise ValueError with
# a message that helps the model try again.
# ---------------------------------------------------------------------------

def search_evidence(inv: "Investigation", query: str) -> str:
    top_k = inv.case_file.index.search(query)
    if len(top_k) == 0:
        raise ValueError(f"No case files found for query {query}.")
    return "\n".join([f"[{r["doc_id"]}] {r["title"]}: {r["snippet"]}" for r in top_k])


def read_document(inv: "Investigation", doc_id: str) -> str:
    doc = inv.case_file.index.get(doc_id)
    if doc is None:
        documents = ", ".join(inv.case_file.index.document_dict.keys())
        raise ValueError(f"No document with doc id {doc_id} found. Available doc ids: {documents}")
    return doc["text"]


def list_suspects(inv: "Investigation") -> str:
    return "\n".join(f"{s["name"]}: {s["role"]}" for s in inv.case_file.suspects.values())


def check_alibi(inv: "Investigation", suspect: str, time: str) -> str:
    if not datetime.strptime(time, "%H:%M"):
        raise ValueError(f"Time format of {time} is not valid. Should be HH:MM")

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
    if inv.accused is not None:
        raise ValueError("There can only be a single accusation per case file.")
    candidate_suspect = inv.case_file.find_suspect(suspect)
    inv.accused = inv.case_file.suspects[candidate_suspect]["name"]
    if is_culprit(candidate_suspect):
        inv.verdict = "solved"
        return f"""The suspect {inv.accused} could no longer hide it.
            They tried to sneak out the back into the gardens, but to no avail.
            Their time has come and Blackwood Manor is once again free of evil energies.
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
    def __init__(self, case_file: CaseFile, max_turns: int = 8):
        self.case_file = case_file
        self.max_turns = max_turns
        self.messages: list[dict] = []
        self.pending: dict | None = None  # {"tool": ..., "input": ...} while waiting for approval
        self.verdict: str | None = None  # None, "solved" or "failed"
        self.accused: str | None = None

    @property
    def status(self) -> str:
        if self.verdict is not None:
            return self.verdict
        return "awaiting_approval" if self.pending else "investigating"

    # TODO: implement the methods below. You can add helpers (for example one that turns the
    # tool_use blocks of a response into a tool_result message).
    #
    # Both ask() and decide() return a "turn" dict:
    #   {"status": self.status,
    #    "reply": <the model's final text, or None if paused>,
    #    "tool_calls": [{"name": ..., "input": ..., "is_error": ...}, ...],   # tools run during this call
    #    "pending": self.pending}

    def run_tool(self, name: str, tool_input: dict) -> tuple[str, bool]:
        """Run one tool safely. Returns (text, is_error)."""
        raise NotImplementedError

    def ask(self, text: str, model) -> dict:
        """The inspector says something. Run the agent loop until the model answers, asks for a
        risky tool (pause: set self.pending and return), or max_turns model calls are used up.
        Raise InvestigationError unless status is "investigating"."""
        raise NotImplementedError

    def decide(self, approved: bool, model) -> dict:
        """The inspector approves or declines the pending tool call. Send the tool results for the
        paused response (a declined risky tool gets an error result), then continue the loop.
        Raise InvestigationError if nothing is pending."""
        raise NotImplementedError
