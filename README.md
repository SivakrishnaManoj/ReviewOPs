# ReviewOPs

Shared backbone for the three-person, two-day customer-feedback intelligence prototype.
Target repository: https://github.com/SivakrishnaManoj/ReviewOPs

This is the shared starting point for application, data/retrieval, and cloud work.
Create feature branches from `main` and use pull requests for subsequent changes.

## What works now

- FastAPI process health, database readiness, request IDs, and JSON request logs.
- Validated investigation request/response contracts in OpenAPI.
- PostgreSQL + pgvector with a repeatable migration runner.
- Streaming Amazon review inspection, coverage profiling, validation and repeatable PostgreSQL imports.
- A non-root Docker application image and local Docker Compose services.
- GitHub checks, real database integration tests, infrastructure validation, container
  smoke tests, and opt-in AWS publishing/deployment.
- Terraform for S3, ECR, IAM/OIDC, CloudWatch, and an optional ECS Express service.

AI answers, embeddings, approval, and the React frontend are integration
points. They are not implemented or represented as working features. The investigation
endpoint returns HTTP 501 until the AI owner connects it. Cloud RDS and Bedrock access
are not provisioned by this first backbone milestone.

## Amazon data ingestion

Start with a 200-line streaming inspection; no database or model key is needed:

```sh
uv run python -m scripts.amazon_ingest inspect --limit 200 --report data/processed/inspection.json
```

See [pipelines/README.md](pipelines/README.md) for full profiling, product selection,
PostgreSQL loading, cleaning rules, audit reports and coverage limitations. No complete
raw dataset file is cached. Product metadata ingestion remains a separate next step.

## First run: Docker Desktop

From the repository root, on Windows PowerShell, macOS, or Linux:

```sh
docker compose up --build
```

Open http://localhost:8000 and http://localhost:8000/docs.
`/healthz` means the API process is running; `/readyz` also checks PostgreSQL.
Docker Compose waits for PostgreSQL and applies migrations before starting the API.

Stop with Ctrl+C, then `docker compose down`. This preserves local database contents.
`docker compose down -v` deliberately deletes the local database; use it only when you
want a reset. The bundled database password is for local development only.

## Native Python development

Install Python 3.12, uv, and Docker Desktop. Then:

```sh
uv sync --frozen
docker compose up -d db
```

Copy `.env.example` to `.env` (`Copy-Item .env.example .env` in PowerShell, or
`cp .env.example .env` on macOS/Linux), then:

```sh
uv run python -m scripts.migrate
uv run uvicorn reviewops.api:app --reload --port 8000
```

The Docker source mount supports restarting the API after edits with
`docker compose restart api`; the native command above reloads automatically.

## Checks

```sh
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
```

The database test is skipped locally unless `TEST_DATABASE_URL` points to a disposable
test database. CI creates one automatically. Never set that variable to a production
database. Run the container smoke check against a running app:

```sh
uv run python scripts/smoke.py http://localhost:8000
```

Dependencies are pinned in `uv.lock`; Terraform providers in `infra/.terraform.lock.hcl`.
When adding a dependency, edit `pyproject.toml`, run `uv lock`, and commit both files.

## Team ownership

| Owner | Files |
| --- | --- |
| Siva. - cloud and delivery | `infra/`, `.github/`, `Dockerfile`, `compose.yaml`, deployment scripts |
| AI/application Johann J | `src/reviewops/ai/`, API integration, `web/` |
| Data/retrieval Sweta A | `pipelines/`, `src/reviewops/retrieval/`, ingestion and index migrations |
| Shared, agree before changing | `contracts.py`, schema migrations, `pyproject.toml`, `uv.lock` |

Use branches such as `feat/agent-workflow`, `feat/retrieval`, and `chore/cloud-backbone`.
Each person opens a PR into `main`; see [CONTRIBUTING.md](CONTRIBUTING.md).
The first shared milestone is one real question answered with a source citation on the
deployed app. Work against the contract rather than independently changing its shape.

## Cloud setup

Follow [docs/CLOUD_SETUP.md](docs/CLOUD_SETUP.md) in order. AWS delivery is disabled by
default and requires explicitly configured repository variables. No AWS access keys
need to be stored in GitHub. No resources have been created by preparing this scaffold.

Keep the repository private, datasets out of Git, and `.env`/Terraform state out of commits.
See [docs/HANDOFF.md](docs/HANDOFF.md) for integration boundaries and the first-day order.
