# Ingestion commands

Data owner: implement versioned, repeatable ingestion here. Keep raw and processed
data out of Git. Use local `data/` folders or the private S3 bucket. Expose commands
that accept a small row limit for smoke tests. Re-running the same input must not
duplicate reviews. Commit tiny synthetic fixtures instead of dataset extracts.
