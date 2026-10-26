"""Independent source-row checks for the new predicate and aggregate boundaries."""

import copy
import json
import unittest

import numpy as np
import pandas as pd
from app_core.archetype_serving import describe_loadings
from app_core.population import weighted_quantile
from app_core.story_examples import EXAMPLES
from app_core.story_query import AudienceEngine, commercial, normalize_definition, predicate


class QueryChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = AudienceEngine()

    def test_base_and_scenario(self):
        e = self.engine
        self.assertEqual(len(e.players), 38403)
        self.assertEqual(len(e.business), 24990)
        self.assertEqual(commercial(e.business)["cash_cents"], 28369366)
        self.assertEqual(
            e.players.archetype_state.value_counts().to_dict(),
            {"empty_pool": 17765, "scored": 13348, "below_minimum_pool": 7290},
        )

    def test_broader_presets(self):
        e = self.engine
        actual = []
        for ex in EXAMPLES:
            d = normalize_definition(ex["definition"])
            counts = [int((predicate(e.players, d["shared"]) & predicate(e.players, d[s])).sum()) for s in ["a", "b"]]
            actual.append(counts)
        self.assertEqual(actual, [[2109, 3107], [2817, 3883], [2357, 2736], [2430, 1026]])
        self.assertNotIn("activity_band", EXAMPLES[2]["definition"]["shared"])

    def test_three_dimensional_custom_and_exact_median(self):
        e = self.engine
        d = {
            "schema_version": 1,
            "shared": {"history_band": ["H4", "H5"]},
            "a": {
                "activity_band": ["A4", "A5"],
                "engagement_band": ["E3", "E4"],
                "archetype": {"mode": "expressed", "ids": ["A1", "A3"]},
            },
            "b": {"rank_group": ["Medium", "High"]},
        }
        r = e.compare(d)
        p = e.players
        active = p.archetype_active_ids.map(lambda ids: "A1" in ids or "A3" in ids)
        direct = p.loc[
            p.history_band.isin(["H4", "H5"])
            & p.activity_band.isin(["A4", "A5"])
            & p.engagement_band.isin(["E3", "E4"])
            & active
        ]
        self.assertGreater(len(direct), 30)
        self.assertEqual(r["a"]["profiles"], len(direct))
        self.assertAlmostEqual(r["a"]["weighted_mass"], direct.population_weight.sum())
        self.assertEqual(
            r["a"]["total_games_median"], weighted_quantile(direct.total_games, direct.population_weight, 0.5)
        )
        b = e.business
        direct_b = b.loc[
            b.history_band.isin(["H4", "H5"])
            & b.activity_band.isin(["A4", "A5"])
            & b.engagement_band.isin(["E3", "E4"])
            & b.archetype_active_ids.map(lambda ids: "A1" in ids or "A3" in ids)
        ]
        self.assertEqual(r["a"]["synthetic"]["cash_cents"], int(direct_b.cash_cents.sum()))
        self.assertTrue(set(direct.index).issubset(p.index))

    def test_overlap_joint_and_original_base_denominators(self):
        r = self.engine.compare(
            {"schema_version": 1, "a": {"rank_group": ["Medium", "High"]}, "b": {"rank_group": ["High", "Highest"]}}
        )
        high = self.engine.players.loc[self.engine.players.rank_group.eq("High")]
        self.assertEqual(r["intersection"]["profiles"], len(high))
        self.assertFalse(r["identical"])
        for side in ["a", "b"]:
            self.assertAlmostEqual(sum(x["share"] for x in r[side]["joint"]), 1)
            self.assertAlmostEqual(sum(x["share"] for x in r[side]["map"]), r[side]["weighted_base_share"])
            for f in ["activity_band", "engagement_band", "history_band", "rank_group"]:
                self.assertAlmostEqual(sum(x["share"] for x in r[side][f]), 1)

    def test_expression_incidence_and_primary_coverage(self):
        r = self.engine.compare(EXAMPLES[2]["definition"])
        selected = self.engine.players.loc[self.engine.players.archetype_primary_id.eq("A1")]
        expected = (
            selected.loc[selected.archetype_active_ids.map(lambda x: "A6" in x), "population_weight"].sum()
            / selected.population_weight.sum()
        )
        self.assertAlmostEqual(r["a"]["archetypes"]["expressed"][5]["share"], expected)
        self.assertAlmostEqual(sum(x["share"] for x in r["a"]["archetypes"]["expression"]), 1)
        self.assertAlmostEqual(sum(x["share"] for x in r["parent"]["archetypes"]["shares"]), 1)
        self.assertGreater(sum(x["share"] for x in r["b"]["archetypes"]["expressed"]), 1)

    def test_empty_unavailable_and_no_cash(self):
        r = self.engine.compare(
            {
                "schema_version": 1,
                "shared": {"archetype_state": ["empty_pool"]},
                "a": {"archetype": {"mode": "primary", "ids": ["A1"]}},
                "b": {},
            }
        )
        self.assertEqual(r["a"]["profiles"], 0)
        self.assertEqual(r["b"]["archetypes"]["scored"], 0)
        self.assertIsNone(r["a"]["synthetic"]["cash_per_payer"])
        self.assertIsNone(r["a"]["total_games_median"])
        self.assertEqual(sum(x["share"] for x in r["a"]["joint"]), 0)
        json.dumps(r, allow_nan=False)
        nonbuyers = self.engine.business.loc[~self.engine.business.cash_buyer]
        c = commercial(nonbuyers)
        self.assertEqual(c["payer_share"], 0)
        self.assertIsNone(c["repeat_payer_share"])

    def test_threshold_ties_and_diffuse(self):
        model = self.engine.model
        for values, kind, active in [
            ([0.2, 0.199999, 0, 0, 0, 0, 0, 0], "Single", ["A1"]),
            ([0.2, 0.2, 0, 0, 0, 0, 0, 0], "Blend", ["A1", "A2"]),
            ([0.19999, 0, 0, 0, 0, 0, 0, 0], "Diffuse", []),
        ]:
            row = describe_loadings(np.array(values), model)
            self.assertEqual(row["archetype_kind"], kind)
            self.assertEqual(row["archetype_active_ids"], active)
            if values[0] == values[1] or kind == "Diffuse":
                self.assertIsNone(row["archetype_primary_id"])

    def test_validation_and_empty_normalization(self):
        self.assertEqual(normalize_definition({"schema_version": 1, "a": {"rank_group": []}})["a"], {})
        bad = [
            {"schema_version": True},
            {"schema_version": 1, "a": {"garbage": []}},
            {"schema_version": 1, "joint_axes": ["rank_group", "rank_group"]},
            {"schema_version": 1, "a": {"archetype": {"mode": "best_match", "ids": ["A1"]}}},
            {"schema_version": 1, "a": {"main_role": ["Invented"]}},
        ]
        for d in bad:
            with self.assertRaises(ValueError):
                normalize_definition(d)

    def test_display_levels_use_both_complete_sources_without_changing_schema(self):
        actual = self.engine.display_levels()
        self.assertEqual(actual["activity_band"], [f"A{i}" for i in range(1, 6)])
        self.assertEqual(actual["rank_group"], ["Lowest", "Medium", "High", "Highest"])
        # Future snapshots may populate missing/zero states in either source.
        future = AudienceEngine.__new__(AudienceEngine)
        future.players = pd.DataFrame(
            {"activity_band": ["A1"], "engagement_band": ["E1"], "history_band": ["H1"], "rank_group": ["Lowest"]}
        )
        future.business = pd.DataFrame(
            {
                "activity_band": ["A0"],
                "engagement_band": ["Missing"],
                "history_band": ["H0"],
                "rank_group": ["Unrecognized"],
            }
        )
        visible = future.display_levels()
        self.assertEqual(visible["activity_band"], ["A0", "A1"])
        self.assertEqual(visible["engagement_band"], ["E1", "Missing"])
        self.assertEqual(visible["rank_group"], ["Lowest", "Unrecognized"])
        self.assertEqual(
            normalize_definition({"schema_version": 1, "a": {"activity_band": ["A0"]}})["a"], {"activity_band": ["A0"]}
        )

    def test_repeatable_and_identical(self):
        d = {"schema_version": 1, "shared": {"main_role": ["Support"]}}
        a = self.engine.compare(d)
        b = self.engine.compare(copy.deepcopy(d))
        self.assertEqual(a, b)
        self.assertTrue(a["identical"])
        self.assertEqual(a["intersection"]["profiles"], a["a"]["profiles"])
        self.assertTrue(self.engine.business.main_role.equals(self.engine.business.audience_main_role))


if __name__ == "__main__":
    unittest.main()
