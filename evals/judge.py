"""Step 14: an LLM as judge, for what code can't check: is the answer correct and grounded?

A judge model is a function judge(system, prompt) -> str (see harness.FakeJudge and harness.claude_judge).
"""

# Step 14 TODO: write the judge's instructions: its role, a rubric (what makes an answer pass or
# fail), and the exact output format (JSON with "reason" and "verdict": "pass" or "fail").
JUDGE_SYSTEM = """TODO"""


class JudgeParseError(ValueError):
    """The judge's reply has no usable verdict."""


def build_judge_prompt(case: dict, answer: str, evidence: list[dict]) -> str:
    # Step 14 TODO: put the question, the case's reference_answer, the evidence documents
    #   ([{"doc_id", "title", "text"}]) and the answer to grade into one prompt.
    #   Wrap each part in tags: <question>, <reference>, <evidence> and <answer>.
    raise NotImplementedError


def parse_verdict(text: str) -> dict:
    # Step 14 TODO: pull {"verdict": "pass" | "fail", "reason": str} out of the judge's reply.
    #   Real replies are messy: the JSON may sit inside a ```json fence or after some prose,
    #   and "PASS" should count as "pass". Raise JudgeParseError when there's no valid verdict.
    raise NotImplementedError


def judge_answer(case: dict, answer: str | None, evidence: list[dict], judge, retries: int = 1) -> dict:
    # Step 14 TODO: build the prompt (use "(no answer)" for None), call judge(JUDGE_SYSTEM, prompt) and
    #   parse the reply. On a JudgeParseError, try again up to `retries` more times, then return
    #   {"verdict": "error", "reason": <the last error>} instead of crashing the whole eval run.
    raise NotImplementedError
