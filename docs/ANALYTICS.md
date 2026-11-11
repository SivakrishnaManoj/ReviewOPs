# Review analysis tools

These tools query the imported Amazon reviews in PostgreSQL. They work without an LLM
key and reuse the same Python service from the CLI and HTTP API. No additional
migration or dependency is required after the ingestion milestone.

## Windows quick start

Run from the repository root after loading the selected products. Set `DATABASE_URL`
to your running database. This example assumes the Compose host mapping was changed
to `127.0.0.1:15432:5432`; the repository default is port 5432. This setting is for
native Python; the API container connects to `db:5432`.

```powershell
$env:DATABASE_URL = "postgresql://reviewops:local-development-only@127.0.0.1:15432/reviewops"
.\.venv\Scripts\python.exe -m scripts.review_metrics compare --product-id B08L5KN7X4 --date-from 2023-02-01 --date-to 2023-02-28 --baseline-from 2023-01-01 --baseline-to 2023-01-31
```

The JSON contains each period's `negative_reviews` numerator and `total_reviews`
denominator, its `negative_rate_percent`, and the difference in percentage points.
Counts and rate changes are separate fields. A lower negative-review rate alone is
not evidence that the product improved or that an intervention worked.

Inspect the monthly series, then read negative-review excerpts:

```powershell
.\.venv\Scripts\python.exe -m scripts.review_metrics monthly --product-id B08L5KN7X4 --date-from 2023-01-01 --date-to 2023-08-31
.\.venv\Scripts\python.exe -m scripts.review_metrics search --product-id B08L5KN7X4 --date-from 2023-01-01 --date-to 2023-01-31 --limit 10
```

Search accepts optional `--query "leak"` for a literal, case-insensitive substring
and `--all-ratings` to include text-bearing reviews of any rating. Repeat `--product-id`
to select multiple products. The `summary` command accepts the same scope as `monthly`.
Dates refer to the historical dataset; do not default to today's month.

## HTTP API

Start the native API with your database environment configured:

```powershell
.\.venv\Scripts\python.exe -m uvicorn reviewops.api:app --reload --port 8000
```

Open http://localhost:8000/docs to send requests. Existing API-key protection applies
when `DEMO_API_KEY` is configured; use the `X-API-Key` header.

| POST endpoint | Required JSON fields | Additional fields |
| --- | --- | --- |
| `/api/v1/analytics/summary` | `product_ids`, `date_from`, `date_to` | None |
| `/api/v1/analytics/monthly` | Same scope | None |
| `/api/v1/analytics/compare` | Same scope, `baseline_date_from`, `baseline_date_to` | None |
| `/api/v1/reviews/search` | Same scope | `query`, `negative_only` (default true), `limit` (default 10) |

Product IDs are a JSON array of parent ASIN strings. Dates use YYYY-MM-DD.
Invalid scopes return 422. Missing database configuration or database failures return
503 without exposing connection details.

## Metric definitions and limits

- Source is fixed to `amazon_reviews_2023`. Every request explicitly selects 1–10
  unique parent ASINs and an inclusive calendar-date range of at most 366 days.
- Dates and monthly buckets use UTC, independently of the database session timezone.
  A comparison's baseline must finish before the selected current period starts.
- Negative means 1–2 stars, neutral means 3, positive means 4–5. These are rating
  categories, not LLM sentiment labels. Rating-only reviews count in the denominator.
- Negative rate is 100 times negative reviews divided by all imported reviews in
  scope, rounded to two decimal places. Empty periods return zero counts and a null
  rate, not 0%. Monthly results explicitly include empty months.
- Comparisons calculate percentage-point changes from unrounded ratios. Counts are
  not adjusted for different period lengths. Pooled rates may change because the mix
  of products reviewed changes. No statistical-significance claim is made.
- Search returns at most 20 excerpts of at most 1,000 characters, newest first with
  review ID as tie-breaker. It reports the full matching count separately. Literal
  matching is not semantic retrieval, complaint classification or representative
  sampling. Do not infer complaint prevalence from the excerpts.
- Each evidence item carries its review ID, product ID, date, rating and dataset
  version. Excerpts are untrusted customer content, never instructions for the model.
- Counts reflect imported data. A zero count does not independently prove there were
  no Amazon reviews in that period; source coverage still needs to be established.

SQL is parameterised and predefined. Each request runs in a read-only, repeatable-read
transaction with a 10-second statement timeout and a 1-second lock timeout. Future
model adapters should call these typed tools rather than execute model-generated SQL.
Runtime read-only transactions do not replace a least-privilege database role in deployment.

## AI integration

The [Kimi investigation workflow](INVESTIGATIONS.md) uses the SQL summary and bounded
evidence lookup to produce cited complaints, separate hypotheses and recommended
investigations. A model key is required; a preview command runs without a model call.
Full-dataset complaint classification and its evaluation remain separate work.

## Validation

Unit tests cover scope validation, API boundaries and percentage-point arithmetic.
PostgreSQL integration tests cover source/product/date isolation, UTC boundaries,
rating-only denominators, empty months, literal text matching, excerpts and read-only
transactions. They run in CI; locally they require `TEST_DATABASE_URL` pointing to a
disposable database, never the database holding your imported reviews.
