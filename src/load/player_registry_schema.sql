CREATE TABLE IF NOT EXISTS player_state_registry (
    puuid TEXT NOT NULL,
    dataset TEXT NOT NULL, -- "players" or "masteries"
    first_loaded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    claim_status TEXT NOT NULL DEFAULT 'idle', -- 'idle' or 'claimed'
    claimed_by TEXT,
    claimed_at TIMESTAMPTZ,
    PRIMARY KEY (puuid, dataset)
);