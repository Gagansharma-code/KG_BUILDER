-- Migration: add documents table
-- This table is the provenance anchor for all ingested source documents
-- across all parser tiers. electrical_parameters.source_document_id
-- references documents.id.

CREATE TABLE IF NOT EXISTS documents (
    id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_url       TEXT NOT NULL,
    content_hash     VARCHAR(64) NOT NULL,
    document_type    VARCHAR(50) NOT NULL,
    ingestion_tier   INT NOT NULL CHECK (ingestion_tier BETWEEN 0 AND 3),
    title            TEXT,
    manufacturer     VARCHAR(200),
    pipeline_version VARCHAR(20),
    ingested_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(content_hash)
);

CREATE INDEX IF NOT EXISTS idx_documents_type
    ON documents(document_type);

CREATE INDEX IF NOT EXISTS idx_documents_manufacturer
    ON documents(manufacturer)
    WHERE manufacturer IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_documents_ingested_at
    ON documents(ingested_at DESC);
