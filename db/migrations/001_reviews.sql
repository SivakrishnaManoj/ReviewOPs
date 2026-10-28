CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE reviews (
    review_id TEXT PRIMARY KEY,
    product_id TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL,
    rating SMALLINT NOT NULL CHECK (rating BETWEEN 1 AND 5),
    reviewed_at TIMESTAMPTZ NOT NULL,
    dataset_version TEXT NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX reviews_product_time_idx ON reviews (product_id, reviewed_at);

-- Choose the embedding model/dimension together before adding a vector column.
-- Keep source IDs stable; do not expose reviewer identifiers in the UI.
