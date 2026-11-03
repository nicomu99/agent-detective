"""A scorecard and a regression gate.

    python -m evals.scorecard evals/data/runs/v1.jsonl --save evals/data/baseline.json     # record a baseline
    python -m evals.scorecard evals/data/runs/v2.jsonl --baseline evals/data/baseline.json # exit code 1 on a regression

main() prints the scorecard and turns compare() into an exit code, which is all CI needs.

The scorecard includes:
- answers.correct: Share of graded answers with all required and no forbidden phrases.
- answers.cites_sources: Share of graded answers that cite a relevant document.
- answers.judge_pass: Share of graded answers the judge passed.
- agent.pass: Share of runs that passed every agent check.
- agent.safe_accusations: Share of runs with no accusation, or a justified one.
- agent.avg_model_calls: Mean number of model calls per run. Lower is better.
- coverage: Share of golden cases present in the run.
- retrieval.recall@<k>: Mean recall at ``k``.
- retrieval.mrr: Mean reciprocal rank.
"""

import argparse
import json
import sys
from pathlib import Path

from app.domain import CaseFile

from .agent_checks import agent_checks
from .answers import code_checks
from .dataset import load_golden
from .harness import CASE_DIR, GOLDEN, FakeJudge, claude_judge, evidence_for, load_run
from .judge import judge_answer
from .retrieval import evaluate_retrieval

LOWER_IS_BETTER = {"agent.avg_model_calls"}


def mean(values) -> float:
    """Calculates the arithmetic mean, treating booleans as 0/1.

    Args:
        values: Any iterable of numbers or booleans.

    Returns:
        The mean of the values, or 0.0 if there are none.
    """
    values = list(values)
    return sum(values) / len(values) if values else 0.0


def build_scorecard(cases: list[dict], run: dict, index, judge, k: int = 3) -> dict:
    """Runs every eval over a recorded run and collects the results in one flat dict.

    Cases are split into three groups:
    - every golden case: retrieval (live against ``index``) and ``coverage``.
    - cases in the run: the agent checks and the model-call count. This includes the unanswerable
      cases, because those are the ones that test whether the agent accuses without enough evidence.
    - graded cases (in the run and with a ``reference_answer``): the code checks and the judge.

    Args:
        cases: The golden cases, as returned by ``load_golden``.
        run: The recorded run, mapping case id to its record (see ``load_run``).
        index: The evidence index, used for the retrieval evals and as the judge's evidence.
        judge: Any ``judge(system, prompt) -> str``, e.g. ``FakeJudge`` or ``claude_judge``.
        k: The number of hits retrieval is evaluated at.

    Returns:
        A dict mapping metric name to value:
            answers.correct: Share of graded answers with all required and no forbidden phrases.
            answers.cites_sources: Share of graded answers that cite a relevant document.
            answers.judge_pass: Share of graded answers the judge passed.
            agent.pass: Share of runs that passed every agent check.
            agent.safe_accusations: Share of runs with no accusation, or a justified one.
            agent.avg_model_calls: Mean number of model calls per run. Lower is better.
            coverage: Share of golden cases present in the run.
            retrieval.recall@<k>: Mean recall at ``k``.
            retrieval.mrr: Mean reciprocal rank.
    """
    code_check_dicts = []
    judge_answer_dicts = []
    agent_checks_dicts = []
    model_calls = []
    coverage = 0
    for case in cases:
        case_id = case["id"]
        if case_id not in run:
            continue
        r = run[case_id]
        answer = r["answer"]
        model_calls.append(r["model_calls"])
        agent_checks_dicts.append(agent_checks(case, r))
        coverage += 1

        if case["reference_answer"] is None:
            continue
        evidence = evidence_for(index, case)
        judge_answer_dicts.append(judge_answer(case, answer, evidence, judge))
        code_check_dicts.append(code_checks(case, answer))
    retrieval_dict = evaluate_retrieval(index, cases, k)
    answers_correct = mean([c["includes"] and c["excludes"] for c in code_check_dicts])
    answers_cites_sources = mean([c["cites"] for c in code_check_dicts])
    answers_judge_pass = mean([c["verdict"] == "pass" for c in judge_answer_dicts])
    agent_pass = mean([a["passed"] for a in agent_checks_dicts])
    agent_safe_accusations = mean([a["accusation_ok"] for a in agent_checks_dicts])
    agent_model_calls = mean(model_calls)
    coverage = coverage / len(cases) if len(cases) > 0 else 0
    ret_dict = {
        "answers.correct": answers_correct,
        "answers.cites_sources": answers_cites_sources,
        "answers.judge_pass": answers_judge_pass,
        "agent.pass": agent_pass,
        "agent.safe_accusations": agent_safe_accusations,
        "agent.avg_model_calls": agent_model_calls,
        "coverage": coverage,
        f"retrieval.recall@{k}": retrieval_dict[f"recall@{k}"],
        "retrieval.mrr": retrieval_dict["mrr"],
    }
    return ret_dict


def compare(baseline: dict, current: dict, tolerance: float = 0.02) -> list[str]:
    """Lists every metric that got worse than the baseline by more than the tolerance.

    Higher is better for every metric except those in ``LOWER_IS_BETTER``. A metric that is in the
    baseline but missing from the current scorecard counts as a regression. Metrics that only exist
    in the current scorecard are ignored.

    Args:
        baseline: A scorecard from ``build_scorecard``, usually loaded from the saved baseline file.
        current: The scorecard to check.
        tolerance: How much worse a metric may get before it counts as a regression.

    Returns:
        One human-readable line per regression, e.g. ``"agent.pass: 1.000 -> 0.800"``. Empty if
        nothing regressed.
    """
    ret = []
    for metric_key, base_val in baseline.items():
        if metric_key not in current:
            ret.append(f"metric {metric_key} is missing for new model")
            continue
        current_val = current[metric_key]
        if (metric_key in LOWER_IS_BETTER and current_val - base_val > tolerance) or (
            metric_key not in LOWER_IS_BETTER and base_val - current_val > tolerance
        ):
            ret.append(f"{metric_key}: {base_val:.3f} -> {current_val:.3f}")
    return ret


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Score a recorded run and compare it with a baseline."
    )
    parser.add_argument("run", type=Path)
    parser.add_argument(
        "--baseline",
        type=Path,
        help="fail (exit code 1) if any metric got worse than this",
    )
    parser.add_argument(
        "--save", type=Path, help="write the scorecard here, e.g. as the new baseline"
    )
    parser.add_argument("--judge", choices=["fake", "claude"], default="fake")
    parser.add_argument("--k", type=int, default=3)
    args = parser.parse_args(argv)

    case_file = CaseFile.load(CASE_DIR)
    cases = load_golden(GOLDEN, {d["doc_id"] for d in case_file.index.documents})
    judge = claude_judge if args.judge == "claude" else FakeJudge(seed=0)
    scores = build_scorecard(
        cases, load_run(args.run), case_file.index, judge, k=args.k
    )
    baseline = json.loads(args.baseline.read_text()) if args.baseline else {}

    print(f"Scorecard for {args.run} ({len(cases)} golden cases)\n")
    for metric, value in scores.items():
        delta = f"  ({value - baseline[metric]:+.3f})" if metric in baseline else ""
        print(f"  {metric:<26} {value:7.3f}{delta}")
    if args.save:
        args.save.write_text(json.dumps(scores, indent=2) + "\n")
        print(f"\nSaved to {args.save}")
    if not args.baseline:
        return 0
    regressions = compare(baseline, scores)
    if regressions:
        print("\nREGRESSIONS:")
        for r in regressions:
            print(f"  - {r}")
        return 1
    print("\nNo regressions.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
