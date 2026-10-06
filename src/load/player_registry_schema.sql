CREATE TABLE IF NOT EXISTS player_state_registry (
    puuid TEXT NOT NULL,
    region TEXT NOT NULL,
    queue TEXT NOT NULL,
    first_loaded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    queue_games_total INTEGER,
    inactive_streak INTEGER NOT NULL DEFAULT 0,
    claim_status TEXT NOT NULL DEFAULT 'idle', -- 'idle' or 'claimed'
    claimed_by TEXT,
    claimed_at TIMESTAMPTZ,
    PRIMARY KEY (puuid, region, queue)
);

ALTER TABLE player_state_registry
    ADD COLUMN IF NOT EXISTS queue_games_total INTEGER;
ALTER TABLE player_state_registry
    ADD COLUMN IF NOT EXISTS inactive_streak INTEGER NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_player_state_registry_queue
    ON player_state_registry (region, queue, last_updated_at)
    WHERE claim_status = 'idle';
CREATE INDEX IF NOT EXISTS idx_player_state_registry_claimed_queue
    ON player_state_registry (claimed_at)
    WHERE claim_status = 'claimed';

CREATE TABLE IF NOT EXISTS rank_page_progress (
    region TEXT NOT NULL,
    queue TEXT NOT NULL,
    tier TEXT NOT NULL,
    division TEXT NOT NULL,
    patch TEXT NOT NULL,
    current_page INTEGER NOT NULL DEFAULT 1,
    loop_count INTEGER NOT NULL DEFAULT 0,
    last_player_count INTEGER NOT NULL DEFAULT 0,
    players_seen INTEGER NOT NULL DEFAULT 0,
    pages_fetched INTEGER NOT NULL DEFAULT 0,
    claim_token TEXT,
    claimed_at TIMESTAMPTZ,
    last_updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (region, queue, tier, division, patch)
);

CREATE INDEX IF NOT EXISTS idx_rank_page_progress_claimed
    ON rank_page_progress (claimed_at)
    WHERE claim_token IS NOT NULL;
