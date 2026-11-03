"""The golden dataset.

evals/data/golden.jsonl holds one test case per line. A case looks like this:

    {"id": "time-of-death",
     "category": "fact",                       # one of CATEGORIES
     "question": "When did Lord Blackwood die, according to the coroner?",
     "relevant_docs": ["coroner-report"],
        # case files a good answer needs ([] if none)
     "must_include": [["22:30"], ["23:00"]],
        # every group must match; any phrase in a group will do;
        # phrases in a section are or, between sections and
     "must_not_include": [],                   # phrases a correct answer never contains
     "reference_answer":
        "Between 22:30 and 23:00, from digitalis poisoning (coroner-report).",
            # what a human would accept, for the judge (null: don't judge)
     "agent": {
        "useful_tools": ["search_evidence", "read_document"],
            # at least one should be used
        "may_accuse": false}}           # is proposing an accusation acceptable here?
"""

import json
from json import JSONDecodeError
from pathlib import Path

CATEGORIES = {"fact", "alibi", "contradiction", "unanswerable", "accusation"}
REQUIRED = {
    "id",
    "category",
    "question",
    "relevant_docs",
    "must_include",
    "must_not_include",
    "reference_answer",
    "agent",
}


class DatasetError(ValueError):
    """A golden case is malformed. Message should say which case and what is wrong."""


def load_golden(path: Path, known_docs: set[str]) -> list[dict]:
    """Load and validate the golden dataset, one JSON case per line.

    Every case is checked before it is accepted, and the first problem found stops
    loading, so a bad dataset fails loudly instead of quietly skewing eval scores.
    Blank lines are ignored.

    Args:
        path: The JSONL file to read, usually ``evals/data/golden.jsonl``.
        known_docs: Names of the case files that exist (e.g. ``"coroner-report"``).
            Every entry in a case's ``relevant_docs`` must be one of them.

    Returns:
        The cases as dicts, in file order, unchanged from the JSON. See the module
        docstring for the fields.

    Raises:
        DatasetError: If a line is not valid JSON, or a case
            - is missing one of the ``REQUIRED`` fields,
            - reuses an ``id`` seen earlier in the file,
            - has a ``category`` outside ``CATEGORIES``,
            - lists a ``relevant_docs`` entry not in ``known_docs``,
            - has a ``must_include`` that is not a list of lists of phrases,
            - is ``"unanswerable"`` but lists ``relevant_docs``, or
            - has an ``agent`` without a list ``useful_tools`` and a bool
                ``may_accuse``.
    """
    data = []
    seen_ids = set()
    with path.open(encoding="utf-8") as f:
        for idx, line in enumerate(f, start=1):
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
            except JSONDecodeError as e:
                raise DatasetError(
                    f"Line {idx} could not be read. Entry is not valid JSON format."
                ) from e
            missing = REQUIRED - set(raw)
            if missing:
                raise DatasetError(
                    f"Case on line {idx} is missing required columns. "
                    f"Missing: {missing}"
                )
            case_id = raw["id"]
            if case_id in seen_ids:
                raise DatasetError(
                    f"Duplicate case id {case_id}. Case ids must be unique."
                )
            seen_ids.add(case_id)
            if raw["category"] not in CATEGORIES:
                raise DatasetError(
                    f"Case {case_id} contains unknown category {raw['category']}."
                )
            docs = set(raw["relevant_docs"]) - known_docs
            if docs:
                raise DatasetError(f"Case {case_id} contains unknown docs {docs}.")
            if not all(
                isinstance(m, list) and all(isinstance(s, str) for s in m)
                for m in raw["must_include"]
            ):
                raise DatasetError(
                    f"Case {case_id} contains invalid must_include. "
                    "Must be list of list of strings."
                )
            if raw["category"] == "unanswerable" and len(raw["relevant_docs"]) > 0:
                raise DatasetError(
                    f"Case {case_id} has category 'unanswerable', while listing "
                    "relevant docs."
                )
            agent = raw["agent"]
            if not isinstance(agent.get("useful_tools"), list) or not isinstance(
                agent.get("may_accuse"), bool
            ):
                raise DatasetError(
                    f"Case {case_id} does not mention useful tools or may accuse "
                    "for agent."
                )
            data.append(raw)
    return data
