CREATE TABLE IF NOT EXISTS league_pipeline.bronze.players AS
SELECT
    *,
    sha2(
        concat_ws('|', region, queueType, tier, rank, patch, date),
        256
    ) AS state_hash
FROM read_files(
    'dbfs:/Volumes/league_pipeline/landing_zone/players/',
    format => 'parquet'
)
WHERE 1 = 0;

CREATE TABLE IF NOT EXISTS league_pipeline.bronze.masteries AS
SELECT
    *,
    sha2(
        concat_ws('|', region, championId, patch, date),
        256
    ) AS state_hash
FROM read_files(
    'dbfs:/Volumes/league_pipeline/landing_zone/masteries/',
    format => 'parquet'
)
WHERE 1 = 0;