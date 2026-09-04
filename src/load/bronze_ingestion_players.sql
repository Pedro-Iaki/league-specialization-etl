MERGE INTO league_pipeline.bronze.players AS target
USING (
SELECT *, sha2(concat_ws('|', region, queueType, tier, rank, patch, date),256) AS state_hash
FROM read_files('dbfs:/Volumes/league_pipeline/landing_zone/players/',format => 'parquet')
) AS source
ON target.puuid = source.puuid
AND target.state_hash = source.state_hash
WHEN NOT MATCHED THEN
INSERT *;