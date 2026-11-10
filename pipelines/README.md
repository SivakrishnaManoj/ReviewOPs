# Amazon Reviews 2023 ingestion

This first data milestone validates and normalises reviews, identifies duplicates,
profiles product/month coverage, and imports valid records into PostgreSQL. It does
not call Kimi, embed reviews, load product metadata, or implement investigations.

The default input is the publisher's HTTPS `All_Beauty.jsonl.gz` stream. No complete
raw dataset is downloaded or cached. A gzip stream still transfers every byte scanned;
filtering products does not provide server-side filtering. The temporary dedupe index
stores only review IDs and content hashes on disk and is deleted after the run.

## Start with inspection

From the repo root after `uv sync --frozen` (Python 3.12):

```sh
uv run python -m scripts.amazon_ingest inspect --limit 200 --report data/processed/inspection.json
```

No database, model key or AWS credentials are required for inspection. Inspect the
report's `fields_seen`, samples without review text, rejection reasons and product/month
counts. A 200-line inspection is a partial sample, not a valid estimate of category-wide
complaint frequency. `--limit` counts source lines, including rejected and filtered rows.

For full category profiling, explicitly remove the default 200-line cap:

```sh
uv run python -m scripts.amazon_ingest profile --limit 0 --report data/processed/coverage.json
```

This reads the whole category. Choose products with enough reviews and consecutive
months from `product_months`. Profiling keeps product/month counters in memory; it does
not retain review text. `inspect` and `profile` deliberately use the same cleaning rules.
The report contains up to five records with text removed, not raw review examples.

## Import into Postgres

Start PostgreSQL and configure `DATABASE_URL` in your ignored `.env` using `.env.example`.
For local development this repository already supplies `docker compose up -d db`.
For a hosted database use its connection URL with the provider's required TLS settings.
Apply migrations explicitly before importing:

```sh
uv run python -m scripts.migrate
uv run python -m scripts.amazon_ingest ingest --limit 200 --report data/processed/import-smoke.json
```

For a complete scan restricted to your chosen product, replace `B000000001` below with
an actual parent ASIN from the coverage report. Repeat `--product-id` for more products:

```sh
uv run python -m scripts.amazon_ingest ingest --limit 0 --product-id B000000001 --report data/processed/import.json
```

Running the same import again adds no duplicate reviews. Reports distinguish inserts,
already-present rows, within-stream duplicates, conflicting identities and rejected rows.
The default batch size is 500; `--batch-size` accepts 1 through 5000. Each batch is an
atomic transaction. An interrupted run can leave earlier batches committed; rerun the
same input to skip those records. This is replay-from-start recovery, not byte-offset
resume. A forcibly terminated process may leave its run marked `running`; inspect the
last committed counters before retrying. A handled source failure marks the run failed.

If a local fixture/export is used, supply its provenance explicitly:

```sh
uv run python -m scripts.amazon_ingest ingest --input data/raw/subset.jsonl.gz --dataset-version amazon2023-all-beauty-subset-v1 --limit 0
```

Local files may be plain UTF-8 JSONL or gzip. The same validator is used for both local
and remote sources. Files must use the Amazon Reviews 2023 schema, not arbitrary CSV.

## Cleaning policy

- Accept integer ratings 1 through 5, including numeric `2.0`; reject booleans, strings,
  non-finite values and out-of-range/fractional ratings. Negative means 1 or 2 stars.
- Require parent ASIN, variant ASIN and a reviewer identifier for reliable source identity.
- Accept integer millisecond `timestamp` or `sort_timestamp`; reject disagreement when
  both appear. Dates must fall from 1996-01-01 through 2023-09-30 UTC. Preserve historical
  dates; do not label historical coverage as current/live monitoring.
- Decode HTML entities/line breaks, normalise Unicode to NFC and collapse whitespace.
  Do not translate, correct spelling, change sentiment, remove profanity or infer dates.
- Keep reviews with only a rating. Mark `has_text=false`; include them in rating totals,
  exclude them from textual complaint analysis. A title alone counts as text.
- Reject malformed JSON/encoding, invalid field types, prohibited control characters,
  records above 2 MiB, titles above 10,000 characters and bodies above 200,000 characters.
  Oversized records are rejected rather than silently truncated.
- Identity is SHA-256 of the source, reviewer identifier, variant ASIN and timestamp.
  No raw reviewer identifiers, images or profile details are stored. This is a derived
  identity because the source has no native review ID; edited timestamps can evade dedupe.
- Matching identity and normalised content is a duplicate. Matching identity with
  different content is quarantined for review; the first accepted record is retained.
  Identical text from different people is preserved. This is not fake-review detection.

## Audit and coverage

`ingestion_runs` stores the source/version, category, product selection, status and counts.
`ingestion_rejections` stores source line numbers, fixed reason codes and raw-line SHA-256
hashes. It does not store review bodies or credentials. Re-inspect the source file/stream
using the recorded version and line to diagnose an issue; publisher changes can affect
reproducibility, so an immutable archived source would be a later improvement.

`reviews.dataset_version` records the first accepted version. Reruns do not overwrite
it. Per-run duplicate counters show reuse; there is no versioned edit history yet.
An `input_exhausted=true` report means the provided input was consumed. It does not mean
all Amazon reviews exist in this research dataset or that a local subset is comprehensive.
Runs hitting the cap are conservatively marked partial, even if it happens to equal EOF.

```sql
SELECT product_id,
       date_trunc('month', reviewed_at AT TIME ZONE 'UTC') AS month,
       COUNT(*) AS total_reviews,
       COUNT(*) FILTER (WHERE rating <= 2) AS negative_reviews,
       COUNT(*) FILTER (WHERE has_text) AS reviews_with_text,
       ROUND(100.0 * COUNT(*) FILTER (WHERE rating <= 2) / NULLIF(COUNT(*), 0), 2)
         AS negative_percent
FROM reviews
WHERE source = 'amazon_reviews_2023'
GROUP BY product_id, month
ORDER BY product_id, month;
```

The denominator is all imported reviews in each product/month, including rating-only
rows. This query does not claim ingestion or classification coverage beyond that scope.

## Tests

```sh
uv run pytest -q
```

Synthetic tests cover validation, gzip/HTTPS reading without real network requests,
caps, audit counts, privacy-safe errors and dedupe across batches. Real PostgreSQL tests
use `TEST_DATABASE_URL` and are run by CI. Never point it at a production database.

## Source

- Dataset: https://amazon-reviews-2023.github.io/
- Review stream: https://mcauleylab.ucsd.edu/public_datasets/data/amazon_2023/raw/review_categories/All_Beauty.jsonl.gz
- Metadata (next integration): https://mcauleylab.ucsd.edu/public_datasets/data/amazon_2023/raw/meta_categories/meta_All_Beauty.jsonl.gz
- Citation: Hou et al., *Bridging Language and Items for Retrieval and Recommendation*, 2024,
  https://arxiv.org/abs/2403.03952
- Maintainer usage statement: https://huggingface.co/datasets/McAuley-Lab/Amazon-Reviews-2023/discussions/1

Keep raw data, reports, credentials and real-review fixtures out of Git.
