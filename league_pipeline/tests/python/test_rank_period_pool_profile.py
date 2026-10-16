"""Execute the period profile against its champion-activity input contract offline."""

import math
import sqlite3
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from jinja2 import Environment, StrictUndefined

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("points,favoured_count", [([100], 1), ([60, 30, 10], 2), ([25, 25, 25, 25], 4)])
def test_period_profile_aggregates_activity_and_classifies(points, favoured_count):
    variables = yaml.safe_load((PROJECT_ROOT / "dbt_project.yml").read_text(encoding="utf-8"))["vars"]
    environment = Environment(undefined=StrictUndefined)
    environment.globals.update(
        config=lambda **kwargs: "",
        ref=lambda name: name,
        var=lambda name, default=None: variables.get(name, default),
        dbt_utils=SimpleNamespace(
            safe_divide=lambda numerator, denominator: f"1.0 * ({numerator}) / nullif(({denominator}), 0)",
        ),
    )
    scoring = environment.from_string((PROJECT_ROOT / "macros/playstyle_score.sql").read_text(encoding="utf-8"))
    environment.globals["playstyle_score"] = scoring.module.playstyle_score
    query = environment.from_string(
        (PROJECT_ROOT / "models/gold/fct_players_period_pool_profile.sql").read_text(encoding="utf-8"),
    ).render()
    with closing(sqlite3.connect(":memory:")) as connection:
        connection.row_factory = sqlite3.Row
        connection.create_function("least", -1, min)
        connection.create_function("greatest", -1, max)
        connection.create_function("pow", 2, pow)
        connection.create_function("log2", 1, math.log2)
        connection.execute("""
            create table fct_players_period_champion_activity (
                rank_period_id text, champion_key integer, champion_name text,
                points_gained real, champion_share real, points_rank integer,
                favoured_champion_count integer, favoured_log_gap real, is_favoured boolean
            )
        """)
        for rank, gained in enumerate(points, start=1):
            connection.execute(
                "insert into fct_players_period_champion_activity values (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("period", rank, f"Champion {rank}", gained, gained / sum(points), rank,
                 favoured_count, None, rank <= favoured_count),
            )
        rows = connection.execute(query).fetchall()
        connection.execute(f"create table fct_players_period_pool_profile as {query}")
        reconciliation = environment.from_string(
            (PROJECT_ROOT / "tests/business/assert_period_champion_activity_reconciles.sql").read_text(
                encoding="utf-8",
            ),
        ).render()
        assert connection.execute(reconciliation).fetchall() == []
        for column in ("rank_period_favoured_champion_count", "rank_period_favoured_champions_share"):
            connection.execute(f"update fct_players_period_pool_profile set {column} = {column} + 1")
            assert [row[0] for row in connection.execute(reconciliation)] == ["period"]
            connection.execute(f"update fct_players_period_pool_profile set {column} = {column} - 1")

    assert len(rows) == 1
    result = rows[0]
    shares = [value / sum(points) for value in points]
    entropy = -sum(share * math.log2(share) for share in shares)
    assert result["champion_count"] == len(points)
    assert result["mastery_points_gained"] == sum(points)
    assert result["primary_champion_key"] == 1
    assert result["rank_period_top1_share"] == pytest.approx(shares[0])
    assert result["rank_period_favoured_champion_count"] == favoured_count
    assert result["rank_period_favoured_champions_share"] == pytest.approx(sum(shares[:favoured_count]))
    assert result["rank_period_hhi"] == pytest.approx(sum(share ** 2 for share in shares))
    assert result["rank_period_entropy"] == pytest.approx(entropy)
    assert result["rank_period_normalized_entropy"] == pytest.approx(
        entropy / math.log2(len(points)) if len(points) > 1 else 0,
    )
    scores = {name: result[f"{name}_score"] for name in variables["playstyle_profiles"]}
    assert result["rank_period_playstyle"] == max(scores, key=scores.get)
