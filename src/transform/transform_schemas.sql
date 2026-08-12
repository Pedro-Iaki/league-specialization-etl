CREATE TABLE IF NOT EXISTS silver_runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    pipeline_name TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL DEFAULT 'running',
    patch TEXT,
    region TEXT,
    queue TEXT,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS silver_tasks (
    task_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES silver_runs(run_id),
    dataset TEXT NOT NULL,
    file_path TEXT NOT NULL,
    file_hash TEXT,
    processed INTEGER NOT NULL DEFAULT 0,
    processed_at TEXT,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    last_error TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_silver_tasks_unique_path
    ON silver_tasks(dataset, file_path);
