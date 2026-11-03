# Blackwood Manor: a detective agent service

*Saturday 14 November 1931. Lord Edmund Blackwood is found dead in his library. A storm has flooded the only lane, so the killer is still in the house.*

A small FastAPI microservice where you play the inspector. You chat with **Sergeant Wilkes**, an AI agent who searches the case files, checks alibis and, once you approve it, makes the accusation. You get exactly one.

## What's inside

| Part      | What it does                                                                                                                                                                                                                                                            | Where                     |
|-----------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|---------------------------|
| **RAG**   | Splits the case files into paragraphs and ranks them against a query with TF-IDF. Exposed to the agent as a tool and directly over HTTP.                                                                                                                                | `app/domain/evidence.py`  |
| **Agent** | A hand-written tool-use loop (no framework) with five tools: `search_evidence`, `read_document`, `list_suspects`, `check_alibi`, `accuse`. The loop **pauses** when the model wants to `accuse` and resumes when the inspector approves or declines in a later request. | `app/domain/detective.py` |
| **API**   | FastAPI service with env-var config, startup loading via `lifespan`, liveness and readiness probes, Pydantic validation, dependency injection and request-ID logging.                                                                                                   | `app/api/`, `app/main.py` |

The model is pluggable: `fake` (default, a tiny command parser, so no API key is needed) or `claude` (the real agent via the Anthropic API).

## Project structure

```
app/
├── main.py              # create_app(): lifespan, middleware, routers, exception handlers
├── core/                # config.py (Settings), logging.py, middleware.py (X-Request-ID)
├── api/
│   ├── deps.py          # FastAPI dependencies + Annotated aliases
│   ├── errors.py        # domain exceptions -> HTTP status codes
│   └── routes/          # health.py, evidence.py, investigations.py
├── schemas/             # Pydantic request/response models
├── services/            # use cases, no FastAPI imports
├── repositories/        # InvestigationStore (in memory)
└── domain/              # evidence.py (RAG), detective.py (agent), llm.py (models)
case_files/              # the evidence: *.md statements and reports, suspects.json
```

Dependencies point inward: routes call services, and services call the repository and domain. Only `app/api` and `app/main.py` know about FastAPI.

## Setup

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
# install uv once (or: pipx install uv / brew install uv)
curl -LsSf https://astral.sh/uv/install.sh | sh

# create .venv and install the locked dependencies
uv sync
```

To add or update packages, use `uv add <package>` and `uv lock --upgrade`. Commit both `pyproject.toml` and `uv.lock`.

### Configuration

All configuration comes from environment variables, so the same build runs locally, in Docker and in Kubernetes.

| Variable            | Default        | Meaning                                |
|---------------------|----------------|----------------------------------------|
| `DETECTIVE_MODEL`   | `fake`         | `fake` or `claude`                     |
| `ANTHROPIC_API_KEY` | (none)         | Required when `DETECTIVE_MODEL=claude` |
| `CASE_DIR`          | `./case_files` | Folder with the case files             |
| `MAX_TURNS`         | `8`            | Maximum model calls per agent turn     |
| `LOG_LEVEL`         | `INFO`         | Python log level                       |

Invalid values make the service **refuse to start**, so a misconfigured container fails immediately instead of misbehaving later.

## Running locally

```bash
uv run uvicorn app.main:main_app --reload
```

Then open http://127.0.0.1:8000/docs for the interactive API docs. To play with the real agent:

```bash
DETECTIVE_MODEL=claude ANTHROPIC_API_KEY=sk-ant-... uv run uvicorn app.main:app --reload
```

Run the tests with `uv run pytest`.

## Running with K8s and Docker

(optionally) Build a docker image

```bash
docker build -t <image-name>:<image-version> .
```

and push it to your docker hub.

```bash
docker push <image-name>:<image-version>
```

A pre-built image is also publicly available.

Then deploy the Redis Deployment and expose it via a Service:

```bash
kubectl apply -f k8s/redis_deploy.yaml
kubectl apply -f k8s/redis_service.yaml
```

The case files are not baked into the image, so the campaign can be changed without needing to update it. Instead,
the cluster will read them from a ConfigMap:

```bash
kubectl apply -f k8s/config_map.yaml
```

If the config map is not available, run

```bash
kubectl create configmap case_files --dry-run=client --from-file case_files/ -o yaml > k8s/config_map.yaml
```

By default, the application runs in the cluster using the `claude` mode. This requires an API key, which is read form
a Secret. Create a file `.env` with a key-value pair `ANTHROPIC_API_KEY=sk...`. Then run

```bash
kubectl create secret generic anthropic --from-env-file=.env
```

Then apply the deployment. A docker image has already been created.

```bash
kubectl apply -f k8s/deploy.yaml
```

Use port-forwaring to talk to the system from your local machine: 

```bash
kubectl port-forward deployments/agent-detective 8080:8080
```

If you want to play the game locally, without using an LLM, manually delete the `ANTHROPIC_API_KEY` and
`DETECTIVE_MODEL` environment variables from `k8s` and skip creating a Secret.

## Using the API with curl

**Health and readiness**
```bash
curl localhost:8000/health        # {"status":"ok"}: the process is alive
curl localhost:8000/ready         # {"status":"ready","documents":12}: case files are loaded
```

**Search the evidence directly (RAG only, no agent)**
```bash
curl "localhost:8000/evidence/search?q=brandy+decanter&k=3"
curl localhost:8000/evidence/coroner-report
```

**Start an investigation**
```bash
curl -X POST localhost:8000/investigations
# {"investigation_id":"3f9c2a1b7e4d","briefing":"Blackwood Manor, Sunday 15 November 1931..."}

ID=3f9c2a1b7e4d   # use the id you got back
```

**Talk to the detective**
```bash
curl -X POST localhost:8000/investigations/$ID/messages \
     -H "Content-Type: application/json" \
     -d '{"text": "Where was Clara at 22:30?"}'
```
The response holds the agent's `reply`, the `tool_calls` it made, and the investigation's `status`.

With the fake model, send commands instead of questions: `help`, `suspects`, `search grey tweed`, `read maid-statement`, `alibi Clara 22:30`, `accuse <name>`.

**Accuse someone (two steps)**
```bash
curl -X POST localhost:8000/investigations/$ID/messages \
     -H "Content-Type: application/json" -d '{"text": "accuse <name>"}'
# -> "status": "awaiting_approval", "pending": {"tool": "accuse", ...}

curl -X POST localhost:8000/investigations/$ID/approval \
     -H "Content-Type: application/json" -d '{"approved": true}'
# -> "status": "solved" or "failed". There is only one try.
```

**Check or close an investigation**
```bash
curl localhost:8000/investigations/$ID
curl -X DELETE localhost:8000/investigations/$ID
```

Every response carries an `X-Request-ID` header. Send your own (`-H "X-Request-ID: my-test-1"`) to find the request in the logs.

### Status codes

| Code  | When                                                                                                                                |
|-------|-------------------------------------------------------------------------------------------------------------------------------------|
| `201` | Investigation created                                                                                                               |
| `204` | Investigation deleted                                                                                                               |
| `404` | Unknown investigation or document                                                                                                   |
| `409` | Action not allowed right now (asking while an accusation awaits approval, approving when nothing is pending, or the case is closed) |
| `422` | Invalid request (empty text, `k` out of range, `approved` not a boolean)                                                            |
| `503` | `/ready` before startup has finished                                                                                                |

## Evaluation

The evals in `evals/` measure how well the detective retrieves evidence, answers questions and behaves as an agent. They
also compare a new version of the agent against a saved baseline to catch regressions.

> **Spoiler warning:** `evals/data/golden.jsonl` and `evals/data/judge_labels.jsonl` contain the clues and the solution
> to the case. Don't open them if you want to play first.

### The golden dataset

`evals/data/golden.jsonl` holds one test case per line: a question for the detective plus what a good answer
looks like. That covers the case files it should rest on (`relevant_docs`), the phrases it must and must not contain,
a reference answer for the judge, and which tools the agent should use and whether it may accuse. Each case has a
category: `fact`, `alibi`, `contradiction`, `unanswerable` or `accusation`. `evals/dataset.py` validates every case on
load and stops at the first malformed one, so a broken dataset fails loudly. The module docstring documents the full
format.

### What is evaluated

| Eval                  | What it measures                                                                                                                                                                                  | Where                    |
|-----------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|--------------------------|
| **Retrieval**         | Recall@k and mean reciprocal rank of the TF-IDF index against each case's `relevant_docs`. Runs live against `app/`, so it needs no recorded run.                                                  | `evals/retrieval.py`     |
| **Answer checks**     | Plain-code checks on the answer: are the required phrases there, are the forbidden ones absent, and does it cite a relevant case file?                                                             | `evals/answers.py`       |
| **LLM judge**         | A judge model compares the answer with the reference answer and the evidence, and decides whether it is correct, grounded and honest about what the files don't say.                              | `evals/judge.py`         |
| **Judge reliability** | Compares the judge with human-graded answers in `judge_labels.jsonl`: accuracy, Cohen's kappa, false pass and false fail rates, and how consistent the judge is across repeated calls.            | `evals/reliability.py`   |
| **Agent checks**      | Grades what the agent *did*, not only what it said: it used a useful tool, stayed within the model-call budget, had no failing tool calls, and only accused when allowed and after enough evidence. | `evals/agent_checks.py`  |
| **Scorecard**         | Combines everything into one set of metrics and compares them with a baseline.                                                                                                                    | `evals/scorecard.py`     |

The answer, judge and agent evals don't call the detective themselves. They score a **recorded run**: a JSONL file in
`evals/data/runs/` with the detective's answer, tool calls, model-call count and status for each golden question. This
keeps scoring cheap and repeatable, and lets you compare two versions of the agent on exactly the same answers.

### Running the evals

**1. Record a run** of the detective in `app/` over every golden question:

```bash
uv run python -m evals.harness --model fake --out evals/data/runs/fake.jsonl
uv run python -m evals.harness --model claude --out evals/data/runs/mine.jsonl   # needs ANTHROPIC_API_KEY
```

Each question gets a fresh investigation. Accusations are never approved: the run only records that one is pending.

**2. Score the run and save it as the baseline:**

```bash
uv run python -m evals.scorecard evals/data/runs/v1.jsonl --save evals/data/baseline.json
```

**3. Check a new run against the baseline:**

```bash
uv run python -m evals.scorecard evals/data/runs/v2.jsonl --baseline evals/data/baseline.json
```

This prints each metric with its change from the baseline. It exits with code `1` if any metric got worse by more than
`0.02`, or is missing. Higher is better for every metric except `agent.avg_model_calls`.

Useful options are `--judge claude` to use the real judge instead of the default `FakeJudge` (needs
`ANTHROPIC_API_KEY`), and `--k` to set the number of hits for retrieval (default `3`).

**Checking the judge.** Judge reliability isn't part of the scorecard and has no command of its own. Run it from Python:

```bash
uv run python -c '
import json
from app.domain import CaseFile
from evals.dataset import load_golden
from evals.harness import CASE_DIR, DATA, GOLDEN, FakeJudge
from evals.reliability import measure_judge
cf = CaseFile.load(CASE_DIR)
cases = {c["id"]: c for c in load_golden(GOLDEN, {d["doc_id"] for d in cf.index.documents})}
labels = [json.loads(l) for l in (DATA / "judge_labels.jsonl").open() if l.strip()]
print(measure_judge(FakeJudge(seed=0), labels, cases, cf.index))
'
```

Swap `FakeJudge(seed=0)` for `claude_judge` (imported from `evals.harness`) to measure the real judge.

### Things to keep in mind

- **The fake judge and fake model are stand-ins.** They let everything run without an API key, but their scores say
  nothing about the real agent. Use `--model claude` and `--judge claude` for numbers that matter. Both cost API calls.
- **Update the baseline on purpose.** Run `--save` only after a run you've decided is the new standard. Otherwise a
  regression becomes the new normal.
- **Coverage below 1.0** means the run is missing golden cases. Usually the run was recorded before cases were added,
  so record it again.
- **Keep the dataset honest.** When you add a case, check that its `relevant_docs` really hold the answer. Otherwise
  the retrieval and answer metrics measure the dataset, not the agent.