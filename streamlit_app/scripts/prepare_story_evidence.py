"""Prepare public aggregate evidence; no raw logs or player identifiers leave this step."""

import gzip
import json
import re
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
HERE = ROOT / "streamlit_app/story_component"

sys.path.insert(0, str(ROOT / "streamlit_app"))

# The snapshot module establishes the repository app namespace.
# isort: split
from app_core.family_cohort import validate_cohort
from app_core.snapshot_hash import sha256_file


def digest(path):
    return sha256_file(path)


def text_digest(path):
    return sha256_file(path, normalize_newlines=True)


def prepare():
    folder = ROOT / "data/local_lab/final-champion-family-cohort-20261023"
    validation = json.loads((folder / "validation.json").read_text())
    for filename, expected in validation["hashes"].items():
        if digest(folder / filename) != expected:
            raise ValueError(f"Family evidence checksum mismatch: {filename}")
    cohort = json.loads(gzip.decompress((folder / "cohort.json.gz").read_bytes()))
    validate_cohort(cohort, pd.DataFrame(cohort["catalog"]), cohort["membership_sha256"], cohort["reference_sha256"])
    definition = json.loads((ROOT / "streamlit_app/definitions/champion-audience-families-v1.json").read_text())
    memberships = pd.read_csv(folder / "cohort-memberships.csv")
    counts = pd.Series([x["character_key"] for f in definition["families"] for x in f["members"]]).value_counts()
    families = []
    for f in definition["families"]:
        selected = next(x for x in cohort["selected"] if x["id"] == f["candidate_id"])
        if selected["source_id"] != f["source_id"] or set(selected["member_keys"]) != {
            x["character_key"] for x in f["members"]
        }:
            raise ValueError("Selected family identity mismatch")
        source = cohort["sources"][f["source_id"]]
        keys = source["co_membership"]["character_keys"]
        indices = [keys.index(x["character_key"]) for x in f["members"]]
        matrix = np.array(source["co_membership"]["rates"])[np.ix_(indices, indices)]
        fits = (matrix.sum(axis=1) - np.diag(matrix)) / (len(indices) - 1)
        if not np.isclose(fits.mean(), f["saved_evidence"]["mean_consistency"]):
            raise ValueError("Saved matrix and family consistency disagree")
        members = []
        for member, fit in zip(f["members"], fits):
            row = memberships.loc[
                (memberships.character_key == member["character_key"]) & memberships.family_id.eq(f["candidate_id"])
            ].iloc[0]
            if not np.isclose(float(row.member_fit), fit):
                raise ValueError("Membership fit mismatch")
            members.append(
                {"name": member["character"], "fit": float(fit), "overlap": int(counts[member["character_key"]])}
            )
        families.append(
            {
                "id": f["family_key"],
                "title": f["title"],
                "members": members,
                "matrix": matrix.tolist(),
                "repeats": source["repetitions"],
                "source_id": f["source_id"],
                **f["saved_evidence"],
            }
        )
    model = json.loads((ROOT / "streamlit_app/definitions/player-pool-archetypes-v1.json").read_text())
    components = [
        {
            "id": aid,
            "name": name,
            "families": [{"id": fid, "strength": float(v)} for fid, v in zip(model["family_order"], values)],
        }
        for aid, name, values in zip(model["ids"], model["names"], model["profiles"])
    ]
    tradeoffs = pd.read_csv(ROOT / "data/local_lab/relative-floor-sensitivity-20261023/threshold-summary.csv")
    tradeoffs = tradeoffs.loc[
        tradeoffs.feasible.eq(True), ["floor", "covered", "families", "weakest_fit", "mean_consistency"]
    ].to_dict("records")
    runs = []
    for name in ["20261019T072301Z-backlog", "20261020T030508Z-clean"]:
        path = ROOT / "data/evidence" / name
        log = (path / "console.log").read_bytes().decode("utf-16")
        timing = json.loads((path / "invocation-timing.json").read_text(encoding="utf-8-sig"))
        events = []
        for line in log.splitlines():
            timestamp = line[:23]
            if "Starting round " in line:
                events.append({"time": timestamp, "event": re.search(r"Starting round \d+/\d+", line)[0]})
            for phase in ["Ingestion", "dbt"]:
                if phase + " job started" in line or phase + " job completed" in line:
                    events.append(
                        {"time": timestamp, "event": phase + (" started" if "job started" in line else " completed")}
                    )
        rounds = len(re.findall(r"Round \d+ completed\.", log))
        ingestion = len(re.findall("Ingestion job completed", log))
        build = len(re.findall("dbt job completed", log))
        if (rounds, ingestion, build, timing["exit_code"]) != (12, 4, 4, 0):
            raise ValueError("Unexpected archived run summary")
        # Monotonic log event times and alternating start/completion checks per phase.
        if [e["time"] for e in events] != sorted(e["time"] for e in events):
            raise ValueError("Non-monotonic run timeline")
        for phase in ["Ingestion", "dbt"]:
            if [e["event"] for e in events if e["event"].startswith(phase)] != [
                f"{phase} {x}" for _ in range(4) for x in ["started", "completed"]
            ]:
                raise ValueError("Unexpected job phase order")
        runs.append(
            {
                "date": name[:8],
                "rounds": rounds,
                "ingestions": ingestion,
                "builds": build,
                "timing": timing,
                "events": events,
                "sha256": digest(path / "console.log"),
                "note": "Timer start was not captured; initial backlog and execution revision are not authenticated."
                if "19T" in name
                else "Timer and console align. Context was corrected from this archive. Full initial backlog and cold/warm compute state were not captured.",
            }
        )
    ledger = ROOT / "data/evidence/20261019T072301Z-backlog/extraction-after.db"
    with sqlite3.connect(ledger.resolve().as_uri() + "?mode=ro", uri=True) as connection:
        row = connection.execute("""SELECT p.status,c.status,r.player_load_status,c.source_file_count,c.rows_written
            FROM players_recorded r JOIN compaction_tasks c ON c.task_id=r.latest_player_compacted_task_id
            JOIN player_tasks p ON EXISTS (SELECT 1 FROM json_each(r.player_task_ids) WHERE value=p.task_id)
            WHERE r.player_load_status='load_success' AND c.status='success' AND p.status='success' LIMIT 1""").fetchone()
    lineage = {
        "available": bool(row),
        "nodes": ["Recorded source task", "Linked compacted artifact", "Confirmed load"],
        "status": list(row[:3]) if row else [],
        "source_files": row[3] if row else None,
        "rows": row[4] if row else None,
        "note": "One linked example from the October 19 archived SQLite ledger. Local identifiers and paths omitted. This is task/file lineage, not column lineage.",
    }
    result = {
        "families": families,
        "components": components,
        "tradeoffs": tradeoffs,
        "runs": runs,
        "lineage": lineage,
        "family_definition_sha256": text_digest(
            ROOT / "streamlit_app/definitions/champion-audience-families-v1.json"
        ),
        "family_cohort_sha256": digest(folder / "cohort.json.gz"),
    }
    (HERE / "public-evidence.json").write_text(json.dumps(result, allow_nan=False), encoding="utf8")
    publication = {
        "prepared_at": "2026-10-25",
        "source": "Reviewed saved family diagnostics and separate October 19/20 execution archives",
        "files": {
            "public-evidence.json": text_digest(HERE / "public-evidence.json"),
            **{
                name: text_digest(ROOT / "streamlit_app/definitions" / name)
                for name in ["champion-audience-families-v1.json", "player-pool-archetypes-v1.json"]
            },
        },
    }
    (HERE / "evidence-manifest.json").write_text(json.dumps(publication, indent=2), encoding="utf8")
    return result


if __name__ == "__main__":
    data = prepare()
    print(
        f"Prepared {len(data['families'])} verified family matrices, 8 components, 2 run timelines; lineage: {data['lineage']['available']}"
    )
