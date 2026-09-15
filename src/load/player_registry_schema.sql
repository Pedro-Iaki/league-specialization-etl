CREATE TABLE IF NOT EXISTS player_state_registry (
    puuid TEXT PRIMARY KEY,
    dataset TEXT NOT NULL, -- "players" or "masteries"
    first_loaded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);