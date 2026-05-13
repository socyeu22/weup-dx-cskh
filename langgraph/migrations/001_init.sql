CREATE TABLE IF NOT EXISTS conversation_state (
    psid                    TEXT PRIMARY KEY,
    dify_conversation_id    TEXT NOT NULL DEFAULT '',
    handoff_state           TEXT NOT NULL DEFAULT 'bot',
    pancake_conversation_id TEXT NOT NULL DEFAULT '',
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
