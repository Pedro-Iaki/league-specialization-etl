CREATE TABLE IF NOT EXISTS player_state_registry (
    puuid TEXT NOT NULL,
    region TEXT NOT NULL,
    queue TEXT NOT NULL,
    first_loaded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    claim_status TEXT NOT NULL DEFAULT 'idle', -- 'idle' or 'claimed'
    claimed_by TEXT,
    claimed_at TIMESTAMPTZ,
    PRIMARY KEY (puuid, region, queue)
);

CREATE INDEX IF NOT EXISTS idx_player_state_registry_queue
    ON player_state_registry (region, queue, last_updated_at)
    WHERE claim_status = 'idle';
CREATE INDEX IF NOT EXISTS idx_player_state_registry_claimed_queue
    ON player_state_registry (claimed_at)
    WHERE claim_status = 'claimed';