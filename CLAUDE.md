# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

"Blackwood Manor" is a learning exercise built as a FastAPI microservice. The player chats with an AI detective agent ("Sergeant Wilkes") that searches murder-case files and, with approval, makes one accusation. `ex.md` is the exercise brief: Parts 1–3 (RAG, agent, API, steps 1–10), Part 4 (evals, steps 11–17), then Docker/Kubernetes. `check.py` holds the step-by-step checks. `solution/` is a reference solution (currently only `solution/evals`).

Spoiler warning: `case_files/`, `evals/data/golden.jsonl` and `evals/data/judge_labels.jsonl` contain the mystery's clues and answer. `detective.is_culprit` encodes the solution.

## Commands

Uses Python 3.12+ and `uv` (no requirements.txt; `ex.md`'s `pip install -r requirements.txt` is out of date).

```bash
uv sync                                           # install deps (incl. dev group: pytest, httpx)
REDIS_URL=redis://localhost:6379 uv run uvicorn app.main:main_app --reload   # app object is `main_app`, not `app`
uv run python check.py 3                          # check one exercise step (1-17)
uv run python check.py all                        # stops at the first failing step
uv run python check.py 11 --solution              # run a check against the solution/ package instead of app/
uv run python -m evals.harness --model fake --out evals/data/runs/fake.jsonl      # record a run of app/'s detective
uv run python -m evals.scorecard evals/data/runs/v1.jsonl --save evals/data/baseline.json
uv run python -m evals.scorecard evals/data/runs/v2.jsonl --baseline evals/data/baseline.json  # exit 1 on regression
```

There is no pytest suite. `check.py` is the test runner. It needs no API key or Redis server: it uses a scripted model, FastAPI's `TestClient` and an in-memory `FakeRedis` patched into `app.main`. It clears `DETECTIVE_MODEL`, `MAX_TURNS`, `CASE_DIR` and `ANTHROPIC_API_KEY` from the environment. `--solution` only swaps the evals package (steps 11–17), because `solution/` contains only `evals`. Steps 14–17 still need the exercise's TODOs filled in under `evals/`.

Env config (validated in `app/core/config.py`; invalid values abort startup on purpose): `DETECTIVE_MODEL` (`fake` default | `claude`), `ANTHROPIC_API_KEY`, `CASE_DIR`, `MAX_TURNS`, `REDIS_URL` (required), `LOG_LEVEL`.

## Architecture

- **RAG** (`app/domain/evidence.py`): `EvidenceIndex` splits `case_files/*.md` into paragraphs and ranks them with TF-IDF. It is used both as an agent tool and directly by `/evidence` routes.
- **Agent** (`app/domain/detective.py`): a hand-written tool-use loop with no framework. `CaseFile` bundles the index and `suspects.json`. The tools are `search_evidence`, `read_document`, `list_suspects`, `check_alibi` and `accuse`. `Investigation.ask()` and `Investigation.decide()` share `_agent_loop`. When the model calls `accuse`, the loop **pauses** (status `awaiting_approval`) and resumes in a later request via `decide(approved)`. Only one accusation is allowed. `Investigation.to_dict()`/`from_dict()` serialize the full state so it can be stored between requests.
- **Models** (`app/domain/llm.py`): every model is a function `(system, messages, tools) -> response dict`. `fake_model` is a command parser (`help`, `suspects`, `search …`, `read <doc>`, `alibi <name> <time>`, `accuse <name>`). `call_model` calls the Anthropic API.
- **API**: `app/main.py`'s `lifespan` loads settings, the `CaseFile` and a Redis client into `app.state`. `app/api/deps.py` exposes them as dependencies, and `app/api/errors.py` maps domain exceptions to 404/409/422. Only `app/api` and `app/main.py` import FastAPI. `X-Request-ID` middleware lives in `app/core/middleware.py`.
- **Persistence** (`app/repositories/investigation_store.py`): investigations are stored as JSON in Redis under `investigation:<id>`, and every operation is async. The class docstring still describes the old in-memory store.
- **Evals** (`evals/`): one module per exercise step (`dataset`, `retrieval`, `answers`, `judge`, `reliability`, `agent_checks`, `scorecard`). `harness.py` is provided plumbing (`load_run`, `FakeJudge`, `claude_judge`, `record_run`). Answer, judge and agent evals score the recorded runs in `evals/data/runs/*.jsonl`. Retrieval evals run live against `app/`'s `EvidenceIndex`. A judge is any `judge(system, prompt) -> str`.
- **Deploy**: the `Dockerfile` serves on port 8080. In `k8s/`, case files come from a ConfigMap (not baked into the image), the API key comes from the `anthropic` Secret, and Redis has its own Deployment and Service.

## Docs drift

The README mentions an `app/services/` layer that doesn't exist and an `app.main:app` entry point (the real one is `main_app`). `ex.md` still describes the original flat `app/` layout and `requirements.txt`.
