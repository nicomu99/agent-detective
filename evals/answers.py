"""Answer checks in plain code."""
import re


def mentions(text: str, phrase: str) -> bool:
    """Checks whether the given phrase is present in the text.

    Args:
        text: A piece of text.
        phrase: A phrase to be searched in the text.

    Returns:
        True if the given phrase could be found in the text, else False.
    """
    if re.compile(r'\b({0})\b'.format(phrase.lower()), flags=re.IGNORECASE).search(text.lower()):
        return True
    return False


def code_checks(case: dict, answer: str | None) -> dict:
    """Simple pipeline that checks whether the answer contains certain phrases.

    The pipeline checks whether the case file's requirements are met:
    - `must_include`: contains a list of lists. For each list, one phrase must be present in the answer to pass.
    - `must_not_include`: none of these phrases shall be present in the answer.
    - `relevant_docs`: at least one relevant document should be cited in the answer.

    Args:
        case: A dictionary containing one evaluation instance.
        answer: Response of an agent to the query of case.

    Returns:
        A dictionary with boolean flags for each check, as well as a `passed` flag that is true if all other checks
        passed.
    """
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
