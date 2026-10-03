CREATE TABLE posting (
    id bigint PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    source text NOT NULL,
    source_id text NOT NULL,
    raw jsonb NOT NULL,
    content_text text NOT NULL,
    first_seen timestamp NOT NULL default now(),
    last_seen timestamp NOT NULL default now(),
    updated_at timestamp NOT NULL default now(),
    unique(source, source_id)
);