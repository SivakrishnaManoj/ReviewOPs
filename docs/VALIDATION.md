# Validation record — 28 October 2026

Completed in the preparation environment:

- Python 3.12 dependency resolution with a committed `uv.lock`.
- Ruff lint and formatting checks passed.
- 15 Python tests passed: API health/readiness, input validation, credential-safe error
  responses, optional API-key boundary, deployment configuration preservation, rollback,
  and refusal to race an in-flight deployment.
- A live Uvicorn process passed HTTP smoke checks, including the expected build SHA
  and the published API contract.
- Terraform formatting checks passed, and the AWS provider dependency lock was generated.
- The ECS Express Terraform block names were checked against the provider's source.
- Both GitHub workflows passed Actionlint; Compose and GitHub YAML parsed successfully.

Not completed here:

- One real PostgreSQL integration test was skipped because no PostgreSQL service is running.
  CI explicitly starts pgvector/PostgreSQL and runs that test without skipping.
- Docker/Compose smoke tests: Docker is not installed in this preparation environment.
- Full `terraform validate`: the execution environment rejects the Unix socket needed
  for Terraform's provider handshake. This is not an AWS authentication or plan result.
  CI runs full provider validation on its Linux runner.
- GitHub-hosted workflow execution, AWS plan/apply, deployment, and live AWS rollback:
  no authenticated repository/AWS session was available while preparing the scaffold.

The Python test run reports one upstream Starlette/httpx deprecation warning; tests pass.
This record must be updated after the first GitHub and AWS runs. Passing local tests
does not establish a successful cloud deployment.
