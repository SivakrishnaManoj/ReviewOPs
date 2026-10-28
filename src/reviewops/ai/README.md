# AI owner

Implement the LangGraph workflow here and wire it into `reviewops.api.investigate`.
Use `reviewops.contracts` for the HTTP boundary. Keep model calls behind an interface
so unit tests can run without cloud credentials. Persist checkpoints in PostgreSQL.
Approval and task creation must be separate nodes; make writes idempotent.

Add LangGraph and model SDK dependencies to the root `pyproject.toml`, then run
`uv lock` and commit `uv.lock` together. Coordinate any schema changes with the data owner.
