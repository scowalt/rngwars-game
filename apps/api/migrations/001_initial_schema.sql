CREATE TABLE users (
    id            TEXT PRIMARY KEY,
    username      TEXT NOT NULL,
    anonymous_id  TEXT UNIQUE NOT NULL,
    rng_score     INTEGER NOT NULL DEFAULT 1200
                  CHECK (rng_score >= 100 AND rng_score <= 3000),
    total_wins    INTEGER NOT NULL DEFAULT 0,
    total_losses  INTEGER NOT NULL DEFAULT 0,
    total_matches INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    last_seen_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE matches (
    id            TEXT PRIMARY KEY,
    player1_id    TEXT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    player2_id    TEXT REFERENCES users(id) ON DELETE RESTRICT,
    winner_id     TEXT REFERENCES users(id) ON DELETE RESTRICT,
    status        TEXT NOT NULL DEFAULT 'waiting'
                  CHECK (status IN ('waiting', 'active', 'completed', 'forfeited', 'abandoned')),
    is_practice   INTEGER NOT NULL DEFAULT 0,
    ai_name       TEXT,
    player1_roll  REAL,
    player2_roll  REAL,
    player1_elo_before INTEGER,
    player2_elo_before INTEGER,
    player1_elo_after  INTEGER,
    player2_elo_after  INTEGER,
    started_at    TEXT,
    completed_at  TEXT,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX idx_matches_player1 ON matches(player1_id);
CREATE INDEX idx_matches_player2 ON matches(player2_id);
CREATE INDEX idx_matches_created ON matches(created_at DESC);
