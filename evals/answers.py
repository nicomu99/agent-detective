"""Step 13: answer checks in plain code. Cheap, fast and deterministic, so use them wherever they work."""
import re


def mentions(text: str, phrase: str) -> bool:
    if re.compile(r'\b({0})\b'.format(phrase.lower()), flags=re.IGNORECASE).search(text.lower()):
        return True
    return False


def code_checks(case: dict, answer: str | None) -> dict:
    if answer is None:
        return {"includes": True, "excludes": True, "cites": True, "passed": True}

    includes = all(any(mentions(answer, g) for g in m) for m in case["must_include"])
    excludes = all(not mentions(answer, m) for m in case["must_not_include"])
    docs = case["relevant_docs"]
    if not docs:
        cites = True
    else:
        cites = any(mentions(answer, d) for d in docs)
    return {"includes": includes, "excludes": excludes, "cites": cites, "passed": includes and docs and excludes}
