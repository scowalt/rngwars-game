ALTER TABLE users ADD COLUMN auth_provider TEXT;         
ALTER TABLE users ADD COLUMN auth_id       TEXT;         
ALTER TABLE users ADD COLUMN email         TEXT;
ALTER TABLE users ADD COLUMN display_name  TEXT;
ALTER TABLE users ADD COLUMN avatar_url    TEXT;
ALTER TABLE users ADD COLUMN is_anonymous  INTEGER NOT NULL DEFAULT 1;
ALTER TABLE users ADD COLUMN linked_at     TEXT;         


CREATE UNIQUE INDEX idx_users_auth ON users(auth_provider, auth_id)
    WHERE auth_provider IS NOT NULL;
