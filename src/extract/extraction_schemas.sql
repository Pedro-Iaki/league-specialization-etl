-- One row per pipeline execution
CREATE TABLE runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    pipeline_name TEXT NOT NULL,
    started_at TEXT NOT NULL,
	last_heartbeat TEXT,
    finished_at TEXT,
    status TEXT NOT NULL DEFAULT 'running',  -- running, success, failed
    error_message TEXT
);

-- One row per player snapshot extracted, with a reference to the run that created it.
CREATE TABLE player_tasks (
    task_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs(run_id),
    file_path TEXT,
    status TEXT NOT NULL DEFAULT 'pending',  -- pending, in_progress, success, failed
    attempts INTEGER NOT NULL DEFAULT 0,
    started_at TEXT,
    finished_at TEXT,
    error_message TEXT
);

-- One row per mastery task, added at the very start of the bulk mastery processing for better tracking.
CREATE TABLE mastery_tasks (
	task_id INTEGER PRIMARY KEY AUTOINCREMENT,
	run_id INTEGER NOT NULL REFERENCES runs(run_id),
	file_path TEXT UNIQUE,
	player_id TEXT NOT NULL,
	status TEXT NOT NULL DEFAULT 'pending',  -- pending, in_progress, success, failed
	attempts INTEGER NOT NULL DEFAULT 0,
	started_at TEXT,
	finished_at TEXT,
	error_message TEXT
);

-- Every player that has been recorded in the database, along with the paths of the files where they were found and their mastery status.
CREATE TABLE players_recorded (
    player_id TEXT PRIMARY KEY,
    region TEXT,
    queue TEXT,
    tier TEXT,
    division TEXT,
    player_task_ids TEXT NOT NULL, -- JSON array of player_task_ids where this player was found
    paths TEXT, -- JSON array of file paths where this player was found
    paths_logged_at TEXT, -- JSON array of timestamps when this record was logged
    patches_logged TEXT, -- JSON array of patches when this record was logged
    mastery_task_id INTEGER REFERENCES mastery_tasks(task_id), -- reference to the mastery task for this player, if any
    mastery_status TEXT NOT NULL DEFAULT 'pending', -- 'pending', 'in_progress', 'success', 'failed'
	mastery_path TEXT UNIQUE REFERENCES mastery_tasks(file_path), -- path to the mastery file if added, null otherwise
	mastery_logged_at TEXT, -- timestamp when the mastery status was last updated
	mastery_patch TEXT, -- patch when the mastery status was last updated
    latest_player_compacted_task_id INTEGER REFERENCES compaction_tasks(task_id), -- reference to the compaction task for this player's files, if any
    latest_player_compacted_path TEXT,
    mastery_compacted_task_id INTEGER REFERENCES compaction_tasks(task_id), -- reference to the compaction task for this player's mastery file, if any
    mastery_compacted_path TEXT
);

-- Every tier division combination, along with their corresponding pages and player counts.
-- If the last player count is ever higher than the player count found, it means we`ve reached the end and must reset back to 1.
CREATE TABLE tier_division_pages (
	region TEXT NOT NULL,
	queue TEXT NOT NULL,
	tier TEXT NOT NULL,
	division TEXT NOT NULL,
	patch TEXT NOT NULL,
	current_page INTEGER NOT NULL,
	last_player_count INTEGER NOT NULL,
	last_updated_at TEXT NOT NULL,
	loop_count INTEGER NOT NULL DEFAULT 0,
	PRIMARY KEY (region, queue, tier, division, patch)
);

-- One row per compacted partition directory, tracking the small raw files that were merged into a single output file.
CREATE TABLE compaction_tasks (
    task_id INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset TEXT NOT NULL, -- 'players' or 'masteries'
    paths_compressed TEXT, -- JSON array of file paths that were compressed
    output_path TEXT NOT NULL, -- resulting compacted parquet file
    source_file_count INTEGER NOT NULL DEFAULT 0, -- number of small files merged (and later deleted)
    rows_written INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending', -- pending, in_progress, success, failed
    started_at TEXT,
    finished_at TEXT,
    error_message TEXT
);