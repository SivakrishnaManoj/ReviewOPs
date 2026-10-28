# Data and retrieval owner

Put retrieval code here and ingestion commands in `pipelines/`.
Use parameterised SQL, product/date filters, and stable source IDs.
Start with the migration-backed `reviews` table. Add embeddings and index migrations
after agreeing the embedding model and dimension with the AI owner.

Persist ingestion source/version and indexed coverage. Numerical aggregations must
run over the declared SQL scope; retrieval results are supporting examples.
