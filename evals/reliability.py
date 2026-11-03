"""How far can you trust the judge? Compare it with human labels.

evals/data/judge_labels.jsonl holds answers a human has graded:
    {"id": "tod-paraphrase", "case_id": "time-of-death", "answer": "...", "human": "pass", "note": "..."}

The module computes
- the confusion matrix, i.e. the true positive/false positive and true negative/fales negative rate
- Cohen's kappa, i.e. how often two graders agree
- the false positive rate, i.e. the rate of false events marked as positive out of all true negative events
- the false negative rate, i.e. the rate of positive events marked as negative out of all true positive events
- the consistency, i.e. the rate of verdicts, where all judges come to the same verdict (only useful if the judge is
    called multiple times)
- disagreements, a list of cases, where the LLM and human-based judges disagree
"""

from evals.harness import evidence_for

from .judge import judge_answer


def confusion(judge_verdicts: list[str], human_labels: list[str]) -> dict:
    """Counts the judge's verdicts against the human labels, with "pass" as the positive class.

    Any judge verdict other than "pass" (including "error") counts as a fail.

    Args:
        judge_verdicts: The judge's verdict per answer.
        human_labels: The human label per answer, in the same order.

    Returns:
        ``{"tp", "fp", "fn", "tn"}``: true passes, false passes (judge passed, human failed),
        false fails (judge failed, human passed) and true fails.
    """
    tp, fp, fn, tn = 0, 0, 0, 0
    for j, h in zip(judge_verdicts, human_labels):
        if h == "pass":
            if j == h:
                tp += 1
            else:
                fn += 1
        else:
            if j == "pass":
                fp += 1
            else:
                tn += 1
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn}


def cohen_kappa(a: list[str], b: list[str]) -> float:
    """Cohen's kappa: how often two graders agree, corrected for agreement by chance.

    Uses the two-class form computed from the confusion matrix, so anything other than
    "pass" in ``a`` counts as a fail. A judge that passes everything gets 0, however
    high its accuracy.

    Args:
        a: The first-grader's labels, usually the judge's.
        b: The second-grader's labels, usually the human's.

    Returns:
        1.0 for perfect agreement, 0.0 for chance level, -1.0 for perfect disagreement.
        Returns 1.0 when kappa is undefined, i.e. both graders give every answer the same label.
    """
    cm = confusion(a, b)
    tp, fp, tn, fn = cm["tp"], cm["fp"], cm["tn"], cm["fn"]
    denominator = (tp + fp) * (fp + tn) + (tp + fn) * (fn + tn)
    if denominator == 0.0:
        return 1.0
    nominator = 2 * (tp * tn - fn * fp)
    kappa = nominator / denominator
    return kappa


def measure_judge(judge, labels: list[dict], cases_by_id: dict, index, repeats: int = 3) -> dict:
    """Runs the judge on human-graded answers and measures how well it agrees with the human.

    Each answer is judged ``repeats`` times against its golden case and the case's evidence,
    and it counts as a pass only if more than half the repeats pass it.

    Args:
        judge: A judge model, ``judge(system, prompt) -> str``.
        labels: Human-graded answers from ``judge_labels.jsonl``, each with ``case_id``,
            ``answer`` and ``human`` ("pass" or "fail").
        cases_by_id: Golden cases keyed by id. Labels whose case isn't in here are skipped.
        index: The evidence index, used to look up each case's relevant documents.
        repeats: How many times to judge each answer.

    Returns:
        A dict with:
            accuracy: Share of answers where the majority verdict matches the human.
            kappa: Cohen's kappa between the majority verdicts and the human labels.
            false_pass_rate: Share of human-failed answers the judge passed.
            false_fail_rate: Share of human-passed answers the judge failed.
            consistency: Share of answers where all repeats gave the same verdict.
            disagreements: The label ``id`` of every answer where judge and human disagree.
    """
    human_labels = []
    judge_labels = []
    consistency = 0
    disagreement = []
    for label in labels:
        case_id = label["case_id"]
        if case_id not in cases_by_id:
            continue
        case = cases_by_id[case_id]
        evidence = evidence_for(index, case)
        human_labels.append(label["human"])

        judgments = []
        for _ in range(repeats):
            judgments.append(judge_answer(case, label["answer"], evidence=evidence, judge=judge)["verdict"])
        if len(set(judgments)) == 1:
            consistency += 1
        verdict = "pass" if judgments.count("pass") > repeats / 2 else "fail"
        judge_labels.append(verdict)
        if verdict != label["human"]:
            disagreement.append(label["id"])
    cm = confusion(judge_labels, human_labels)
    tp, fp, tn, fn = cm["tp"], cm["fp"], cm["tn"], cm["fn"]

    accuracy = (tp + tn) / (tp + tn + fp + fn) if (tp + tn + fp + fn) > 0 else 0
    kappa = cohen_kappa(judge_labels, human_labels)
    false_pass = fp / (fp + tn) if fp + tn > 0 else 0
    false_fail = fn / (fn + tp) if fn + tp > 0 else 0
    consistency = consistency / len(human_labels) if human_labels else 0

    out = {
        "accuracy": accuracy,
        "kappa": kappa,
        "false_pass_rate": false_pass,
        "false_fail_rate": false_fail,
        "consistency": consistency,
        "disagreements": disagreement
    }
    return out
