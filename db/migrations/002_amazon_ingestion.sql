CREATE TABLE ingestion_runs (
    run_id UUID PRIMARY KEY,
    source TEXT NOT NULL,
    dataset_version TEXT NOT NULL,
    category TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('running', 'complete', 'partial', 'failed')),
    selection JSONB NOT NULL,
    summary JSONB NOT NULL DEFAULT '{}',
    started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMPTZ
);

ALTER TABLE reviews ADD COLUMN source TEXT NOT NULL DEFAULT 'legacy';
ALTER TABLE reviews ADD COLUMN source_asin TEXT;
ALTER TABLE reviews ADD COLUMN content_hash TEXT;
ALTER TABLE reviews ADD COLUMN has_text BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE reviews ADD COLUMN verified_purchase BOOLEAN;
ALTER TABLE reviews ADD COLUMN source_line BIGINT;
ALTER TABLE reviews ADD COLUMN ingestion_run_id UUID REFERENCES ingestion_runs(run_id);

CREATE TABLE ingestion_rejections (
    run_id UUID NOT NULL REFERENCES ingestion_runs(run_id),
    line_number BIGINT NOT NULL,
    reason TEXT NOT NULL,
    record_hash TEXT NOT NULL,
    PRIMARY KEY (run_id, line_number)
);

CREATE INDEX reviews_source_product_time_idx ON reviews (source, product_id, reviewed_at);
