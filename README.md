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

```
 client ──► FastAPI routes ──► InvestigationService ──► Investigation (agent loop) ──► model (fake | Claude)
                │                      │                        │
                │                      ▼                        ▼ tools
                │               InvestigationStore        EvidenceIndex (RAG) ◄── case_files/
                ▼
         /evidence/* ──────────────────────────────────────────►┘
```

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
tests/
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
uv run uvicorn app.main:app --reload
```

Then open http://127.0.0.1:8000/docs for the interactive API docs. To play with the real agent:

```bash
DETECTIVE_MODEL=claude ANTHROPIC_API_KEY=sk-ant-... uv run uvicorn app.main:app --reload
```

Run the tests with `uv run pytest`.

## Running with K8s

The case files are not baked into the image, so the campaign can be changed without needing to update it. Instead,
the cluster will read them from a ConfigMap:

```bash
kubectl create configmap case-files --from-file case_files/
```

By default, the application runs in the cluster using the `claude` mode. This requires an API key, which is read form
a Secret. Create a file `.env` with a key-value pair `ANTHROPIC_API_KEY=sk...`. Then run

```bash
kubectl create secret generic anthropic --from-env-file=.env
```

Then apply the deployment. A docker image has already been created.

```bash
kubectl apply -f deploy.yaml
```

Use port-forwaring to talk to the system from your local machine: 

```bash
kubectl port-forward deployments/agent-detective 8080:8080
```

If you want to play the game locally, without using an LLM, manually delete the `ANTHROPIC_API_KEY` and
`DETECTIVE_MODEL` environment variables from `deploy.yaml` and skip creating a Secret.

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

## Roadmap: Docker and Kubernetes

Still to do:

- [x] `Dockerfile` with a multi-stage build using uv (`uv sync --frozen --no-dev`), running as a non-root user, started with `uvicorn app.main:app --host 0.0.0.0 --port 8000`
- [x] `.dockerignore` (`.venv`, `__pycache__`, `.git`)
- [x] Decide whether the case files are baked into the image or mounted as a volume, with `CASE_DIR` pointing at them
- [ ] Kubernetes manifests: `Deployment`, `Service`, `ConfigMap`, `Secret`
- [ ] Replace the in-memory `InvestigationStore` with Redis, because with more than one replica the next request can hit a pod that has never seen the investigation