# Kimi complaint investigations

The pipeline is explicit: validate scope, fetch SQL metrics and evidence in one
read-only snapshot, close the database connection, call Kimi once, validate the
structured result and citations, then attach the original SQL metrics.

This is a deterministic workflow, not yet a LangGraph agent, semantic retriever or
full-dataset complaint classifier. It answers a scoped complaint-investigation
question using up to 20 newest negative-review excerpts. It cannot establish causes
or explain a change in complaint themes across months.

## Preview first: no API key or model charge

Run from the repository root with the virtual environment already installed.
The database URL below assumes your local Compose port mapping is 15432; the
repository default is 5432.

~~~powershell
$env:DATABASE_URL = "postgresql://reviewops:local-development-only@127.0.0.1:15432/reviewops"
.\.venv\Scripts\python.exe -m scripts.investigate --product-id B08L5KN7X4 --date-from 2023-01-01 --date-to 2023-01-31 --preview
~~~

The preview shows metrics, eligible negative text-review count, selected reviews
and whether excerpts were truncated. It makes no model request.

## Configure Kimi locally

Create a key in the [Kimi API Platform](https://platform.kimi.ai).
Use a Moonshot API key with access to the selected model and billing enabled.
The ordinary Kimi chat subscription is not used by this code.
K3.1 Pro requires a successful account top-up (the documented minimum is $1).
K2 models are unavailable to newly registered accounts. The default is now K3.1 Pro.
Enter the key into PowerShell's hidden prompt so the literal secret does not enter
your command history:

~~~powershell
$kimiSecret = Read-Host "Moonshot API key" -AsSecureString
$env:MOONSHOT_API_KEY = [System.Net.NetworkCredential]::new("", $kimiSecret).Password
Remove-Variable kimiSecret
$env:KIMI_MODEL = "kimi-k3.1-pro"
~~~

Alternatively, put MOONSHOT_API_KEY and KIMI_MODEL in the .env file at the repository
root (C:\Users\sivkr\Desktop\ReviewOPs\.env on this setup), not .env.example.
The local .env is ignored by Git. Existing process environment variables override it:
replace any earlier KIMI_MODEL=kimi-k2.6 setting with kimi-k3.1-pro.
Never paste a key in
chat or commit it. Keys remain in process environment for that terminal session.
Docker Compose does not automatically forward arbitrary host environment variables:
use the native CLI/server for this milestone, or explicitly configure container
secrets before deploying.

## Generate the report: one paid model call

This sends your question, selected review excerpts, product IDs, review IDs, dates
and coverage metadata to Moonshot. Database credentials are never sent to the model.

~~~powershell
.\.venv\Scripts\python.exe -m scripts.investigate --product-id B08L5KN7X4 --date-from 2023-01-01 --date-to 2023-01-31
~~~

Optional: provide --question with a scoped complaint question. Product IDs and dates
remain authoritative even if the question requests another scope. Use explicit
historical dates, not "this month", for the Amazon dataset.

The JSON response separates:

| Field | Meaning |
| --- | --- |
| findings | Reported complaints, review IDs and exact supporting quotes |
| suggested_explanations | Unproven hypotheses linked to complaints |
| recommended_actions | Proposed investigations, in model-suggested priority order, with rationale |
| metrics | SQL counts and negative-review percentage with its denominator |
| coverage | Eligible and selected evidence counts and excerpt truncation |
| sources | The selected excerpts for manual checking |
| model_run | Model, prompt version, latency and provider token usage |
| limitations | Sampling, attribution and validation limits |

No actions are executed. Recommendations have not been approved or persisted.
Metrics are attached by server code; the model cannot overwrite them. Prompts prohibit
numerical claims in narrative fields, but semantic compliance is not guaranteed.
Do not treat narrative counts or prevalence claims as verified metrics.

## API

Start the native server after setting the environment variables:

~~~powershell
.\.venv\Scripts\python.exe -m uvicorn reviewops.api:app --reload --port 8000
~~~

POST /api/v1/investigations accepts question, product_ids, date_from and date_to.
Use http://localhost:8000/docs for the schema. When DEMO_API_KEY is set, include it
in the X-API-Key header. Non-local APP_ENV values require a nonempty DEMO_API_KEY
before the paid endpoint will run. Keep the native development server on localhost.

Request validation now uses the same Amazon scope rules as analytics: 1–10 unique
ten-character parent ASINs and an inclusive UTC date range of at most 366 days.
The previous unimplemented response contract now includes metrics, coverage,
explanations, actions and model metadata.

## Failure behaviour

- No negative text evidence: return insufficient_evidence with SQL metrics and no model call.
- No supported complaint in the model output: insufficient_evidence, with model usage.
- Unknown review ID, non-verbatim quote or broken complaint reference: reject the
  report, returning 502 with invalid_citations. Do not silently drop bad claims.
- Invalid JSON, unexpected fields, oversized output or incomplete generation:
  reject the report. No fabricated fallback answer.
- Missing database/key: 503 with a configuration message. Provider authentication,
  rate limits and connectivity failures are redacted; timeouts return 504.

There are no automatic retries. Each invocation uses at most one model call with
an 8,192 completion-token cap (including reasoning) for K3 models, a socket timeout (default 60 seconds), and a 256 KiB
response cap. The timeout is an I/O timeout, not a guaranteed end-to-end deadline.
Inputs contain at most 20 excerpts of at most 1,000 characters each. Hosted use still
needs per-user quotas, distributed rate limits and operational cost controls.

## Tests and quality evaluation

CI uses synthetic reviews and mocked HTTP responses; it spends no model credits.
Tests cover successful reports, exact quote/ID checks, fabricated citations, linked
complaints, malformed/truncated JSON, empty evidence, abstention, timeout/auth/rate-limit
errors, preview mode, API protection and closing SQL transactions before model calls.
Existing PostgreSQL integration tests check the metrics and evidence selection.

The injection-like text in the synthetic fixture tests how data is passed and
validated. It does not demonstrate live prompt-injection resistance. Exact citations
also do not prove the quote entails the model's statement.

Before claiming model quality, manually label a fixed evaluation set and measure:
complaint precision/recall, citation entailment, hypothesis/action separation,
unsupported claims, abstention, adversarial review handling, latency and token usage.
Version the labels and prompt/model configuration. A live model call has not been
performed merely by passing the offline tests.

Full complaint percentages need a separate classification stage with stored,
versioned labels, evaluation, and SQL aggregation. Do not calculate them from this
newest-review selection.

## Provider references

Checked against the official documentation:

- [API quickstart](https://platform.kimi.ai/docs/get-your-api-key)
- [Kimi K3.1 Pro](https://platform.kimi.ai/docs/guide/kimi-k3-1-pro-quickstart)
- [Model parameters](https://platform.kimi.ai/docs/api/models-overview)
- [JSON mode](https://platform.kimi.ai/docs/guide/use-json-mode-feature-of-kimi-api)

The adapter uses the official api.moonshot.ai endpoint with JSON mode. K3 models
use reasoning_effort=low and max_completion_tokens=8192, without the K2 thinking
parameter or explicit sampling settings. The legacy K2.6 override retains thinking
disabled and max_tokens=4096 for existing accounts. Live model quality and latency
still need validation; an output cap may produce an incomplete report, which is
rejected without an automatic retry.
