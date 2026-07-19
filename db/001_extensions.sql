-- Runs automatically on first container start (docker-entrypoint-initdb.d).
-- pgvector powers profile<->issue fit-matching in Phase 4.
CREATE EXTENSION IF NOT EXISTS vector;
