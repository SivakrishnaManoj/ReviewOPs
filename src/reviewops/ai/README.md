# Complaint investigation workflow

investigate.py orchestrates SQL evidence preparation, a single configured model call and strict
citation checks. gemini.py is the default adapter; kimi.py remains optional; models.py defines its
bounded JSON output. The HTTP boundary remains in reviewops.contracts.

SQL metrics never come from the model. Unknown IDs, fabricated quotes, malformed
output and broken complaint references fail closed. Exact quotes are not proof of
semantic entailment; human evaluation remains necessary.

See [the investigation guide](../../../docs/INVESTIGATIONS.md) for setup and limits.
Tests mock the model and use synthetic fixtures; no API key is needed in CI.

This milestone uses deterministic orchestration without LangGraph or checkpointing.
Later additions can wrap these stages in graph nodes, persist versioned complaint
labels, evaluate quality and add approval/task creation as separate idempotent steps.
No external action is performed by the current model workflow.
