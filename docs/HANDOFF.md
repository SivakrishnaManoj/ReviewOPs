# First-day handoff

## First hour: S.

1. Start from the backbone on `main` in the private repo.
2. Add the two collaborators and ask each to run `docker compose up --build`.
3. Confirm all three can reach `/docs`, `/healthz`, and `/readyz` locally.
4. Run CI once. Enable branch rules after the check names exist.
5. Agree the request contract, source identifiers, date semantics, and embedding model.

Teammates can start immediately; AWS provisioning is independent of local development.

## AI/application owner

- Keep the public endpoint `/api/v1/investigations` and the shared Pydantic contracts.
- `product_ids` correspond to `reviews.product_id` (Amazon parent ASIN).
- Request dates are inclusive calendar dates; SQL should translate the upper bound to
  the start of the next day in UTC to avoid excluding most of the final day.
- Connect LangGraph behind the API. Keep retrieval and SQL as typed, bounded tools.
- Add checkpointing, then approval; only an approved, idempotent write creates a task.
- Add UI build checks and the Docker frontend stage when `web/` is ready.

## Data/retrieval owner

- Implement a row-limited ingestion command first. Persist `dataset_version` and stable IDs.
- Use `reviews.review_id` for all citations; agree the deterministic ID recipe with the AI owner.
- Add migrations for embeddings after choosing dimensions; pgvector is already installed.
- Keep analytical coverage separate from semantic-index coverage and return both explicitly.
- Add synthetic fixtures and small deterministic SQL/retrieval tests to CI.

## S.: cloud milestone sequence

1. Green local app and PR checks.
2. Private state bucket, ECR, OIDC, and application IAM roles.
3. Publish a checked container; create the first HTTPS ECS service.
4. Merge a harmless application change and verify the deployed `build_sha` changes.
5. Add private RDS, a separate migration/admin identity and restricted application user,
   database security groups, and a Secrets Manager `DATABASE_URL`.
6. Configure Bedrock access and a model-specific task-role policy with the AI owner.
7. Before public AI access, configure authentication and server-side request/token/step limits.

The first scaffold does not create RDS, grant inference permissions, add a React build,
or claim production readiness. Those are explicit next integrations, not silent defaults.

## Acceptance demo for the backbone

- A fresh clone starts locally without AWS credentials.
- A broken test prevents image promotion.
- An image is built once, smoke-tested, and the same image is pushed to ECR.
- A merge on main updates the HTTPS endpoint to the expected commit.
- A failed post-deploy smoke check attempts rollback only when ECS is stable.
- CI logs and a deployment manifest identify exactly which image was shipped.
