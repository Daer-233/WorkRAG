CREATE TABLE IF NOT EXISTS manual_session_memory (
    session_key TEXT PRIMARY KEY,
    sources JSONB NOT NULL DEFAULT '[]',
    pending TEXT,
    offered_file BOOLEAN NOT NULL DEFAULT false,
    expires_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    turn_id UUID UNIQUE,
    host_boot UUID,
    turn_expires_at TIMESTAMPTZ,
    retrieval JSONB
);
CREATE INDEX IF NOT EXISTS manual_session_memory_expiry ON manual_session_memory(expires_at);
ALTER TABLE manual_session_memory ADD COLUMN IF NOT EXISTS file_claimed BOOLEAN NOT NULL DEFAULT false;
