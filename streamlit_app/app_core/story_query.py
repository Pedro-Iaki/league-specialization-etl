"""Snapshot-only canonical audience predicates and aggregate summaries for the Streamlit story."""

import hashlib
import json
from pathlib import Path

import pandas as pd

from app_core.archetype_serving import load_model, model_metadata, select_archetype, validate_archetypes
from app_core.audience_segments import prepare_segments, rank_context
from app_core.config import APP_ROOT
from app_core.config import REPO_ROOT as ROOT
from app_core.customer_audiences import prepare_customers
from app_core.population import effective_sample_size, weighted_quantile

IDS = [f"A{i}" for i in range(1, 9)]
LEVELS = {
    **{
        field: [f"{prefix}{i}" for i in range(6)] + ["Missing"]
        for field, prefix in [("activity_band", "A"), ("engagement_band", "E"), ("history_band", "H")]
    },
    "rank_group": ["Lowest", "Medium", "High", "Highest", "Unrecognized"],
    "main_role": ["Top", "Jungle", "Middle", "Bottom", "Support", "Missing"],
    "archetype_state": ["scored", "empty_pool", "below_minimum_pool", "uncovered_pool", "unavailable_pool"],
    "archetype_kind": ["Single", "Blend", "Diffuse", "Missing"],
}
AXES = ["activity_band", "engagement_band", "history_band", "rank_group"]


def normalize_definition(value):
    if not isinstance(value, dict) or set(value) - {"schema_version", "shared", "a", "b", "joint_axes"}:
        raise ValueError("Unknown comparison fields")
    if type(value.get("schema_version")) is not int or value["schema_version"] != 1:
        raise ValueError("Unsupported schema version")
    axes = value.get("joint_axes", ["activity_band", "rank_group"])
    if not isinstance(axes, list) or len(axes) != 2 or any(x not in AXES for x in axes) or axes[0] == axes[1]:
        raise ValueError("Choose two different behavioral axes")
    result = {"schema_version": 1, "joint_axes": axes}
    for side in ["shared", "a", "b"]:
        spec = value.get(side, {})
        if not isinstance(spec, dict) or set(spec) - {*LEVELS, "archetype", "primary_required"}:
            raise ValueError("Unknown audience filter")
        out = {}
        for key, vals in spec.items():
            if key == "primary_required":
                if type(vals) is not bool:
                    raise ValueError("Primary eligibility must be boolean")
                if vals:
                    out[key] = True
            elif key == "archetype":
                if (
                    not isinstance(vals, dict)
                    or set(vals) != {"mode", "ids"}
                    or vals["mode"] not in ["primary", "expressed"]
                ):
                    raise ValueError("Invalid interest selection")
                items = vals["ids"]
                if not isinstance(items, list) or any(x not in IDS for x in items):
                    raise ValueError("Unknown interest ID")
                if items:
                    out[key] = {"mode": vals["mode"], "ids": sorted(set(items))}
            else:
                if not isinstance(vals, list) or any(x not in LEVELS[key] for x in vals):
                    raise ValueError(f"Invalid {key} selection")
                if vals:
                    out[key] = [x for x in LEVELS[key] if x in vals]
        result[side] = out
    return result


def predicate(frame, spec):
    mask = pd.Series(True, index=frame.index)
    for key, vals in spec.items():
        if key == "primary_required":
            mask &= frame.archetype_primary_id.notna() & frame.archetype_kind.ne("Diffuse")
        elif key == "archetype":
            matched = pd.Series(False, index=frame.index)
            for aid in vals["ids"]:
                matched |= select_archetype(frame, aid, vals["mode"])
            mask &= matched
        else:
            mask &= frame[key].astype(object).fillna("Missing").isin(vals)
    return mask


def mass_info(frame):
    weights = frame.population_weight
    return {
        "profiles": len(frame),
        "weighted_mass": float(weights.sum()),
        "effective_n": float(effective_sample_size(weights)) if len(frame) else 0,
    }


def distribution(frame, field, levels):
    total = float(frame.population_weight.sum())
    groups = grouped_mass(frame, [field])
    rows = []
    for code in levels:
        info = groups.get((code,), {"profiles": 0, "weighted_mass": 0.0, "effective_n": 0.0})
        rows.append(
            {field: code, **info, "share": info["weighted_mass"] / total if total else 0, "status": cell_status(info)}
        )
    return rows


def cell_status(info):
    return (
        "empty"
        if not info["profiles"]
        else "available"
        if info["profiles"] >= 30 and info["effective_n"] >= 20
        else "limited"
    )


def grouped_mass(frame, fields):
    data = frame[fields].astype(object).fillna("Missing").copy()
    data["mass"] = frame.population_weight
    data["squared"] = frame.population_weight**2
    groups = data.groupby(fields, observed=True, dropna=False).agg(
        profiles=("mass", "size"), weighted_mass=("mass", "sum"), squared=("squared", "sum")
    )
    result = {}
    for key, row in groups.iterrows():
        result[key if isinstance(key, tuple) else (key,)] = {
            "profiles": int(row.profiles),
            "weighted_mass": float(row.weighted_mass),
            "effective_n": float(row.weighted_mass**2 / row.squared) if row.squared else 0.0,
        }
    return result


def joint(frame, axes, denominator):
    x, y = axes
    groups = grouped_mass(frame, axes)
    # Explicit complete grid, retaining zero/missing and sparse mass.
    rows = []
    for a in LEVELS[x]:
        for b in LEVELS[y]:
            info = groups.get((a, b), {"profiles": 0, "weighted_mass": 0.0, "effective_n": 0.0})
            rows.append(
                {
                    x: a,
                    y: b,
                    **info,
                    "share": info["weighted_mass"] / denominator if denominator else 0,
                    "status": cell_status(info),
                }
            )
    return rows


def commercial(frame):
    n = len(frame)
    counts = frame.cash_purchase_count_60d
    payers = counts.gt(0)
    k = int(payers.sum())
    cents = int(frame.cash_cents.sum())
    contents = int(frame.content_purchase_count_alltime.sum())
    return {
        "n": n,
        "payers": k,
        "cash_cents": cents,
        "payer_share": k / n if n else None,
        "cash_per_payer": cents / 100 / k if k else None,
        "repeat_payer_share": float(counts[payers].ge(2).mean()) if k else None,
        "pooled_cosmetic_fraction_alltime": int(frame.cosmetic_purchase_count_alltime.sum()) / contents
        if contents
        else None,
        "content_events": contents,
        "frequency_distribution": [
            {"label": label, "share": float(mask.mean()) if n else 0}
            for label, mask in [
                ("0 events", counts.eq(0)),
                ("1 event", counts.eq(1)),
                ("2 events", counts.eq(2)),
                ("3+ events", counts.ge(3)),
            ]
        ],
    }


class AudienceEngine:
    def __init__(self, candidate=None):
        self.path = Path(candidate) if candidate is not None else APP_ROOT / "data/story"
        self.manifest = json.loads((self.path / "manifest.json").read_text())
        paths = [
            self.path / n
            for n in [
                "player_profiles.parquet",
                "business_players.parquet",
                "audience_segments_reference.json",
                "manifest.json",
            ]
        ]
        paths += [
            ROOT / "streamlit_app/definitions" / n
            for n in ["champion-audience-families-v1.json", "player-pool-archetypes-v1.json"]
        ]
        self.fingerprints = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
        for name in ["players", "business_players"]:
            entry = self.manifest["datasets"][name]
            if entry.get("sha256") and entry["sha256"] != self.fingerprints[entry["file"]]:
                raise ValueError("Candidate manifest hash mismatch")
        self.reference = json.loads((self.path / "audience_segments_reference.json").read_text())
        if self.reference["source_profile_sha256"] != self.fingerprints["player_profiles.parquet"]:
            raise ValueError("Reference snapshot mismatch")
        self.players, _ = prepare_segments(pd.read_parquet(self.path / "player_profiles.parquet"), self.reference)
        b = pd.read_parquet(self.path / "business_players.parquet")
        b.attrs["business_scenario"] = self.manifest["datasets"]["business_players"]["scenario"]
        self.business = prepare_customers(b, self.reference)
        model_entry = self.manifest["pool_archetypes"]
        model_path = self.path / "player-pool-archetypes-v1.json"
        if (
            model_entry["file"] != model_path.name
            or hashlib.sha256(model_path.read_bytes()).hexdigest() != model_entry["file_sha256"]
        ):
            raise ValueError("Frozen archetype artifact differs from its manifest")
        self.model = load_model(model_path)
        for frame in [self.players, self.business]:
            validate_archetypes(frame, model_metadata(self.model), self.model)
        for name in ["players", "business_players"]:
            if self.manifest["datasets"][name]["pool_archetypes"] != model_metadata(self.model):
                raise ValueError("Manifest archetype registration mismatch")
        if (
            self.manifest["audience_segments_reference"]["sha256"]
            != self.fingerprints["audience_segments_reference.json"]
        ):
            raise ValueError("Manifest reference mismatch")
        # Select on current attached traits; never the original scenario's role.
        self.business["main_role"] = self.business.audience_main_role
        self.names = dict(zip(IDS, self.model["names"]))
        self.base_mass = float(self.players.population_weight.sum())

    def summary(self, frame, customers, axes):
        d = mass_info(frame)
        d["weighted_base_share"] = d["weighted_mass"] / self.base_mass
        for field in AXES:
            d[field] = distribution(frame, field, LEVELS[field])
        d["map"] = joint(frame, ["activity_band", "engagement_band"], self.base_mass)
        d["joint"] = joint(frame, axes, d["weighted_mass"])
        d["rank_activity"] = []
        for rank in LEVELS["rank_group"]:
            part = frame.loc[frame.rank_group.eq(rank)]
            d["rank_activity"] += [
                {**r, "rank_group": rank} for r in distribution(part, "activity_band", LEVELS["activity_band"])
            ]
        for field in ["lifetime_mastery_points", "total_games", "oldest_retained_play_days"]:
            valid = frame.loc[pd.to_numeric(frame[field], errors="coerce").notna()]
            d[field + "_median"] = (
                float(weighted_quantile(valid[field], valid.population_weight, 0.5)) if len(valid) else None
            )
        scored = frame.loc[frame.archetype_state.eq("scored")]
        categories = scored.archetype_primary_id.fillna("Tied strongest").where(
            scored.archetype_kind.ne("Diffuse"), "No strong match"
        )
        scored_mass = float(scored.population_weight.sum())
        primary = [
            {
                "label": self.names.get(a, a),
                "id": a,
                "share": float(scored.loc[categories.eq(a), "population_weight"].sum()) / scored_mass
                if scored_mass
                else 0,
                "profiles": int(categories.eq(a).sum()),
            }
            for a in [*IDS, "No strong match", "Tied strongest"]
        ]
        expressed = [
            {
                "id": a,
                "label": self.names[a],
                "share": float(scored.loc[select_archetype(scored, a, "expressed"), "population_weight"].sum())
                / scored_mass
                if scored_mass
                else 0,
                "profiles": int(select_archetype(scored, a, "expressed").sum()),
            }
            for a in IDS
        ]
        d["archetypes"] = {
            "scored": len(scored),
            "effective_n": mass_info(scored)["effective_n"],
            "coverage": distribution(frame, "archetype_state", LEVELS["archetype_state"]),
            "expression": distribution(scored, "archetype_kind", ["Single", "Blend", "Diffuse"]),
            "shares": primary,
            "expressed": expressed,
        }
        d["synthetic"] = commercial(customers)
        return d

    def compare(self, value):
        definition = normalize_definition(value)
        pshared = predicate(self.players, definition["shared"])
        bshared = predicate(self.business, definition["shared"])
        pm = {k: pshared & predicate(self.players, definition[k]) for k in ["a", "b"]}
        bm = {k: bshared & predicate(self.business, definition[k]) for k in ["a", "b"]}
        result = {"definition": definition, "fingerprints": self.fingerprints}
        for key, pmask, bmask in [("parent", pshared, bshared), *[(k, pm[k], bm[k]) for k in ["a", "b"]]]:
            result[key] = self.summary(self.players.loc[pmask], self.business.loc[bmask], definition["joint_axes"])
        result["intersection"] = {
            **mass_info(self.players.loc[pm["a"] & pm["b"]]),
            "customers": int((bm["a"] & bm["b"]).sum()),
        }
        result["intersection"]["weighted_base_share"] = result["intersection"]["weighted_mass"] / self.base_mass
        result["identical"] = bool(pm["a"].equals(pm["b"]) and bm["a"].equals(bm["b"]))
        return result

    def bootstrap(self):
        from app_core.story_examples import EXAMPLES

        defaults = {e["id"]: self.compare(e["definition"]) for e in EXAMPLES}
        all_data = self.compare({"schema_version": 1})["parent"]
        return {
            "examples": EXAMPLES,
            "defaults": defaults,
            "presets": {"all": all_data},
            "rank_reference": rank_context(self.reference).to_dict("records"),
            "names": self.names,
            "levels": LEVELS,
            "display_levels": self.display_levels(),
            "fingerprints": self.fingerprints,
        }

    def display_levels(self):
        """Freeze display categories against both full populations, never a selection."""
        return {
            field: [
                code
                for code in LEVELS[field]
                if self.players[field].eq(code).any() or self.business[field].eq(code).any()
            ]
            for field in AXES
        }
