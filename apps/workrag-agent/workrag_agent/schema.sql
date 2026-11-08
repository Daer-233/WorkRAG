CREATE TABLE IF NOT EXISTS wa_sessions (
 session_key TEXT PRIMARY KEY, identity JSONB NOT NULL, pending JSONB,
 refs JSONB NOT NULL DEFAULT '[]', updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS wa_answers (
 id UUID PRIMARY KEY, workspace TEXT NOT NULL, actor_key TEXT NOT NULL,
 session_key TEXT NOT NULL REFERENCES wa_sessions(session_key), event_id TEXT NOT NULL,
 question TEXT NOT NULL, answer TEXT NOT NULL, refs JSONB NOT NULL DEFAULT '[]',
 revision INTEGER NOT NULL DEFAULT 1, card_id TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 UNIQUE(session_key,event_id), UNIQUE(workspace,card_id)
);
CREATE TABLE IF NOT EXISTS wa_feedback_events (
 workspace TEXT NOT NULL, event_id TEXT NOT NULL, answer_id UUID NOT NULL,
 actor_key TEXT NOT NULL, vote TEXT NOT NULL CHECK(vote IN ('positive','negative','unknown')),
 reason TEXT NOT NULL DEFAULT '', created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 PRIMARY KEY(workspace,event_id)
);
CREATE TABLE IF NOT EXISTS wa_feedback (
 answer_id UUID NOT NULL REFERENCES wa_answers(id), actor_key TEXT NOT NULL,
 vote TEXT NOT NULL, reason TEXT NOT NULL DEFAULT '', updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 PRIMARY KEY(answer_id,actor_key)
);
CREATE TABLE IF NOT EXISTS wa_candidates (
 id UUID PRIMARY KEY, workspace TEXT NOT NULL, answer_id UUID UNIQUE,
 question TEXT NOT NULL, answer TEXT NOT NULL, refs JSONB NOT NULL,
 conditions TEXT NOT NULL DEFAULT '', state TEXT NOT NULL DEFAULT 'pending',
 privacy_checked BOOLEAN NOT NULL DEFAULT false, revision INTEGER NOT NULL DEFAULT 1,
 review_reason TEXT NOT NULL DEFAULT '', created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS wa_review_events (
 id BIGSERIAL PRIMARY KEY, candidate_id UUID NOT NULL, workspace TEXT NOT NULL,
 action TEXT NOT NULL, revision INTEGER NOT NULL, snapshot JSONB NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS wa_history_actor ON wa_answers(workspace,actor_key,created_at);
CREATE INDEX IF NOT EXISTS wa_qa_published ON wa_candidates(workspace,state);
ALTER TABLE wa_answers ADD COLUMN IF NOT EXISTS simulation BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE wa_candidates ADD COLUMN IF NOT EXISTS simulation BOOLEAN NOT NULL DEFAULT false;
