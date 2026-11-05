CREATE TABLE IF NOT EXISTS manual_departments (
    id UUID PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    dingtalk_department_id TEXT UNIQUE
);

CREATE TABLE IF NOT EXISTS manual_department_grants (
    department_id UUID NOT NULL REFERENCES manual_departments(id),
    target_department_id UUID NOT NULL REFERENCES manual_departments(id),
    PRIMARY KEY (department_id, target_department_id)
);

CREATE TABLE IF NOT EXISTS manual_department_aliases (
    dingtalk_department_id TEXT PRIMARY KEY,
    department_id UUID NOT NULL REFERENCES manual_departments(id)
);

CREATE TABLE IF NOT EXISTS manual_entry_scope (
    entry_id UUID PRIMARY KEY REFERENCES manual_entries(id) ON DELETE CASCADE,
    company_wide BOOLEAN NOT NULL DEFAULT false,
    confirmed BOOLEAN NOT NULL DEFAULT false
);

CREATE TABLE IF NOT EXISTS manual_entry_departments (
    entry_id UUID NOT NULL REFERENCES manual_entries(id) ON DELETE CASCADE,
    department_id UUID NOT NULL REFERENCES manual_departments(id),
    PRIMARY KEY (entry_id, department_id)
);

CREATE TABLE IF NOT EXISTS manual_department_contexts (
    id UUID PRIMARY KEY,
    department_ids TEXT[] NOT NULL DEFAULT '{}',
    expires_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS manual_department_contexts_expiry ON manual_department_contexts(expires_at);
