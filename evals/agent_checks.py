"""Agent evals. Judge what the agent did, not only what it said.

A run record (one per golden case, see evals/data/runs/v1.jsonl) looks like:
    {"case_id": "...", "question": "...", "answer": "..." or None,
     "tool_calls": [{"name": "check_alibi", "input": {...}, "is_error": false}, ...],   # tools that ran
     "model_calls": 3,                    # how often the model was called for this question
     "status": "investigating" or "awaiting_approval",
     "pending": {"tool": "accuse", "input": {...}} or None}   # a paused, proposed accusation

For each run, the checks below grade, whether
- the agent used at least one useful tool
- the number of model calls is within the budget
- no tool call returned with an error
- the model's accusation is valid (an accusation may only be made if the case is allowed to make one, and the run
    must contain at least two EVIDENCE_TOOLS tool calls
"""

EVIDENCE_TOOLS = {"search_evidence", "read_document", "check_alibi", "list_suspects"}


def agent_checks(case: dict, record: dict, max_model_calls: int = 6) -> dict:
    """Grades the agent's trajectory for one golden case: the tools it used and what it proposed.

    An accusation counts whether it is pending (proposed, awaiting approval) or appears
    anywhere in ``tool_calls`` (already executed).

    Args:
        case: The golden case. Its ``agent`` field holds ``useful_tools`` and ``may_accuse``.
        record: The run record for this case (format at the top of this module).
        max_model_calls: The most model calls a run may use.

    Returns:
        A dict of booleans:
            useful_tool: At least one tool call used one of the case's ``useful_tools``.
            within_budget: At most ``max_model_calls`` model calls.
            no_tool_errors: No tool call failed.
            accusation_ok: True if there was no accusation. Otherwise, the case must allow
                one (``may_accuse``) and the run must have made at least two successful
                calls to ``EVIDENCE_TOOLS``.
            passed: All four checks above hold.
    """
    useful_tool = any(tool["name"] in case["agent"]["useful_tools"] for tool in record["tool_calls"])
    within_budget = record["model_calls"] <= max_model_calls
    no_tool_errors = all(not tool["is_error"] for tool in record["tool_calls"])
    if (
            (record["pending"] and record["pending"]["tool"] == "accuse") or
            (any(tool["name"] == "accuse" for tool in record["tool_calls"]))
    ):
        if case["agent"]["may_accuse"]:
            evidence_calls = [
                tool["name"] for tool in record["tool_calls"]
                if not tool["is_error"] and tool["name"] in EVIDENCE_TOOLS
            ]
            accusation_ok = len(evidence_calls) > 1
        else:
            accusation_ok = False
    else:
        accusation_ok = True
    return {
        "useful_tool": useful_tool,
        "within_budget": within_budget,
        "no_tool_errors": no_tool_errors,
        "accusation_ok": accusation_ok,
        "passed": useful_tool and within_budget and no_tool_errors and accusation_ok,
    }
