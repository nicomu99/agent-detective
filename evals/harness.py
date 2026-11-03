"""Plumbing around your evals.

    load_run(path)              read a recorded run (one JSON line per golden case) into {case_id: record}
    evidence_for(index, case)   the full text of a case's relevant documents, for the judge
    FakeJudge(seed, noise)      a stand-in judge model, so no API key is needed
    claude_judge(system, prompt)  the real judge (needs ANTHROPIC_API_KEY)
    record_run(...)             run the detective on every golden question and record what it did

A judge model is any function judge(system: str, prompt: str) -> str.

Record a fresh run of the detective (app/) from the command line:

    python -m evals.harness --model fake --out evals/data/runs/fake.jsonl
    python -m evals.harness --model claude --out evals/data/runs/mine.jsonl     # needs ANTHROPIC_API_KEY
"""

import argparse
import json
import random
import re
from pathlib import Path

from app.domain import llm

ROOT = Path(__file__).resolve().parent.parent
CASE_DIR = ROOT / "case_files"
DATA = Path(__file__).resolve().parent / "data"
GOLDEN = DATA / "golden.jsonl"
STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "did",
    "do",
    "does",
    "for",
    "from",
    "had",
    "has",
    "have",
    "he",
    "her",
    "his",
    "how",
    "i",
    "if",
    "in",
    "is",
    "it",
    "its",
    "me",
    "my",
    "of",
    "on",
    "or",
    "she",
    "so",
    "that",
    "the",
    "their",
    "them",
    "there",
    "they",
    "this",
    "to",
    "was",
    "we",
    "were",
    "what",
    "when",
    "where",
    "which",
    "who",
    "will",
    "with",
    "you",
    "your",
}


def tokenize(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOPWORDS]


def load_run(path: Path) -> dict[str, dict]:
    """A recorded run, as {case_id: {"case_id", "question", "answer", "tool_calls", "model_calls", "status",
    "pending"}}."""
    records = [
        json.loads(line)
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return {r["case_id"]: r for r in records}


def evidence_for(index, case: dict) -> list[dict]:
    """The case's relevant documents as [{"doc_id", "title", "text"}]. Empty for unanswerable questions."""
    return [index.get(doc_id) for doc_id in case["relevant_docs"]]


# ---------------------------------------------------------------------------
# Judges
# ---------------------------------------------------------------------------


def claude_judge(system: str, prompt: str) -> str:
    """Ask Claude to grade. Returns its raw text, which your parse_verdict() has to read."""
    response = llm.call_model(
        system, [{"role": "user", "content": prompt}], tools=[], max_tokens=2000
    )
    return "\n".join(b["text"] for b in response["content"] if b["type"] == "text")


def _tag(prompt: str, name: str) -> str | None:
    match = re.search(rf"<{name}>(.*?)</{name}>", prompt, re.DOTALL)
    return match.group(1).strip() if match else None


class FakeJudge:
    """Pretends to be an LLM judge. It reads the <reference>, <answer> and <evidence> tags from your
    prompt and grades with a crude rule: pass if the answer contains enough of the reference's
    words, and every number or time in the answer also appears in the question, the reference or
    the evidence.

    Like real judges, it isn't perfect:
      - it has a verbosity bias: long answers tend to pass, unless the system prompt tells it
        not to reward length,
      - it misses correct answers that use different words than the reference,
      - with noise > 0, borderline cases come out differently from call to call,
      - it doesn't always answer with clean JSON.
    """

    def __init__(self, seed: int = 0, noise: float = 0.0):
        self.rng = random.Random(seed)
        self.noise = noise
        self.calls = 0

    def __call__(self, system: str, prompt: str) -> str:
        self.calls += 1
        question, reference = _tag(prompt, "question") or "", _tag(prompt, "reference")
        answer, evidence = _tag(prompt, "answer"), _tag(prompt, "evidence") or ""
        if reference is None or answer is None:
            return (
                "I'm sorry, I can't find what to grade. Put the answer in <answer> tags and the reference in "
                "<reference> tags."
            )

        ref_words = set(
            tokenize(re.sub(r"\(.*?\)", "", reference))
        )  # ignore "(coroner-report)" citations
        overlap = len(ref_words & set(tokenize(answer))) / max(len(ref_words), 1)
        unsupported = [
            n
            for n in re.findall(r"\d{1,2}:\d{2}|\d+", answer)
            if n not in reference + question + evidence
        ]
        length_rule = re.search(
            r"\b(length|long|longer|verbose|verbosity)\b", system, re.IGNORECASE
        )

        if len(answer) > 350 and not length_rule:
            verdict, reason = (
                "pass",
                "A thorough and detailed answer that covers the question well.",
            )
        elif unsupported:
            verdict, reason = (
                "fail",
                f"The answer states {', '.join(unsupported)}, which the evidence doesn't support.",
            )
        elif overlap >= 0.45:
            verdict, reason = "pass", "The answer agrees with the reference."
        else:
            verdict, reason = "fail", "The answer misses key facts from the reference."
        if self.noise and abs(overlap - 0.45) < 0.15 and self.rng.random() < self.noise:
            verdict = "pass" if verdict == "fail" else "fail"
            reason = "On balance, " + reason[0].lower() + reason[1:]

        body = json.dumps({"reason": reason, "verdict": verdict})
        style = self.rng.randrange(3)
        if style == 0:
            return body
        if style == 1:
            return f"```json\n{body}\n```"
        return (
            f"Let me compare the answer with the reference and the evidence.\n\n{body}"
        )


# ---------------------------------------------------------------------------
# Recording a run
# ---------------------------------------------------------------------------


def record_run(cases: list[dict], case_file, model, max_turns: int = 6) -> list[dict]:
    """Ask the detective (app/) every golden question in a fresh investigation and record what happened.
    Accusations are never approved: the record just shows that one is pending."""
    from app.domain import detective

    records = []
    for case in cases:
        calls = 0

        def counted(system, messages, tools):
            nonlocal calls
            calls += 1
            return model(system, messages, tools)

        turn = detective.Investigation(case_file, max_turns=max_turns).ask(
            case["question"], counted
        )
        records.append(
            {
                "case_id": case["id"],
                "question": case["question"],
                "answer": turn["reply"],
                "tool_calls": turn["tool_calls"],
                "model_calls": calls,
                "status": turn["status"],
                "pending": turn["pending"],
            }
        )
    return records


def main(argv=None):
    from app.domain import CaseFile

    from .dataset import load_golden

    parser = argparse.ArgumentParser(
        description="Record a run of the detective over the golden dataset."
    )
    parser.add_argument("--model", choices=["fake", "claude"], default="fake")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    case_file = CaseFile.load(CASE_DIR)
    cases = load_golden(GOLDEN, {d["doc_id"] for d in case_file.index.documents})
    model = llm.call_model if args.model == "claude" else llm.fake_model
    records = record_run(cases, case_file, model)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        "".join(json.dumps(r) + "\n" for r in records), encoding="utf-8"
    )
    print(f"Recorded {len(records)} cases to {args.out}")


if __name__ == "__main__":
    main()
