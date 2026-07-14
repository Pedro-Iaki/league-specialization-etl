-- One row per pipeline execution
CREATE TABLE runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    pipeline_name TEXT NOT NULL,
    started_at TEXT NOT NULL,
	last_heartbeat TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL DEFAULT 'running',  -- running, success, failed
    error_message TEXT
);

-- One row per player snapshot extracted, with a reference to the run that created it.
CREATE TABLE player_tasks (
    task_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs(run_id),
    file_path TEXT,
	region TEXT NOT NULL,
	queue TEXT NOT NULL,
	tier TEXT NOT NULL,
	division TEXT NOT NULL,
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
	region TEXT NOT NULL,
	queue TEXT NOT NULL,
	tier TEXT NOT NULL,
	division TEXT NOT NULL,
	player_id TEXT NOT NULL,
	duplicated BOOL DEFAULT 0,
	status TEXT NOT NULL DEFAULT 'pending',  -- pending, in_progress, success, failed
	attempts INTEGER NOT NULL DEFAULT 0,
	started_at TEXT,
	finished_at TEXT,
	error_message TEXT
);

-- Every player that has been recorded in the database, along with the paths of the files where they were found and their mastery status.
CREATE TABLE players_recorded (
    player_id TEXT PRIMARY KEY,
	player_task_ids TEXT NOT NULL, -- JSON array of player_task_ids where this player was found
    paths TEXT NOT NULL, -- JSON array of file paths where this player was found
    paths_logged_at TEXT NOT NULL, -- JSON array of timestamps when this record was logged
	mastery_task_id INTEGER REFERENCES mastery_tasks(task_id), -- reference to the mastery task for this player, if any
    mastery_status TEXT NOT NULL, -- 'pending', 'in_progress', 'success', 'failed'
	mastery_path TEXT UNIQUE REFERENCES mastery_tasks(file_path), -- path to the mastery file if added, null otherwise
	mastery_logged_at TEXT -- timestamp when the mastery status was last updated
);