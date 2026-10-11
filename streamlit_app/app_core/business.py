"""Public allowlist and small business chart summaries; no private join keys."""
from __future__ import annotations

import pandas as pd

CASH_DISCOUNT_COLUMNS = {
    "cash_discounted_purchase_count_60d", "cash_discount_share_60d", "cash_discount_mean_60d",
}
TENURE_ORDER = ["Under 1 year", "1–3 years", "3+ years"]
AUDIENCE_DIMENSIONS = {
    "Tier": "tier", "Role": "main_role", "Playstyle": "active_playstyle",
    "Account age (simulated)": "tenure_band", "Total playtime (estimated)": "playtime_band",
}
PLAYTIME_ORDER = ["Lowest playtime", "Lower playtime", "Mid-range playtime", "Higher playtime", "Highest playtime"]
EXPERIENCE_METRICS = {
    "usd_per_player": "Synthetic recent USD per player",
    "usd_per_purchaser": "Synthetic recent USD per cash purchaser",
    "cash_purchaser_share": "Synthetic recent cash purchaser share",
}

BUSINESS_PUBLIC_COLUMNS = [
    "scenario_id", "as_of_date", "snapshot_date", "purchase_window_start", "purchase_window_end",
    "tier", "main_role", "active_playstyle", "active_primary_champion_name",
    "active_normalized_entropy", "active_top1_share", "alltime_top1_share",
    "total_mastery_points", "champions_with_mastery", "ranked_mastery_share", "games_per_day_recent",
    "simulated_owned_champions", "simulated_customer_type", "first_purchase_at", "last_purchase_at",
    "purchase_count_alltime", "be_champion_purchase_count_alltime", "cash_purchase_count_alltime",
    "cash_spent_usd_alltime", "cash_active_months_alltime", "payment_frequency_alltime",
    "payment_intensity_alltime", "payment_consistency_alltime", "cash_purchase_count_60d",
    "cash_spent_usd_60d", "cash_active_months_60d", "last_cash_purchase_at_60d",
    "days_since_last_cash_purchase_60d", "content_purchase_count_alltime", "cosmetic_purchase_count_alltime",
    "cosmetic_bias_alltime", "discounted_purchase_count_alltime", "discount_share_alltime", "discount_mean_alltime",
    "cash_discounted_purchase_count_60d", "cash_discount_share_60d", "cash_discount_mean_60d",
]
SYNTHETIC_CAPTION = (
    "Purchase history and spending patterns are synthetic; player traits are from the real collected snapshot. "
    "Group differences reflect editable scenario assumptions, not findings about Riot customers."
)


def tier_purchasers(frame: pd.DataFrame) -> pd.DataFrame:
    data = frame.assign(cash_buyer=frame["cash_purchase_count_60d"].gt(0))
    result = data.groupby("tier", observed=True).agg(
        players=("cash_buyer", "size"), cash_purchasers=("cash_buyer", "sum")
    ).reset_index()
    result["cash_purchaser_share"] = result["cash_purchasers"] / result["players"]
    return result


def tenure_spending(frame: pd.DataFrame) -> pd.DataFrame:
    days = (pd.to_datetime(frame["as_of_date"]) - pd.to_datetime(frame["first_purchase_at"], utc=True).dt.tz_localize(None)).dt.days
    data = frame.assign(
        tenure_band=pd.cut(days, [0, 365, 3 * 365, float("inf")], right=False,
                           labels=["Under 1 year", "1–3 years", "3+ years"]),
        purchaser_usd=frame["cash_spent_usd_60d"].astype(float).where(frame["cash_purchase_count_60d"].gt(0)),
    )
    return data.groupby("tenure_band", observed=True).agg(
        players=("cash_purchase_count_60d", "size"),
        cash_purchasers=("purchaser_usd", "count"),
        mean_usd_per_cash_purchaser=("purchaser_usd", "mean"),
    ).reset_index()


def with_tenure(frame: pd.DataFrame) -> pd.DataFrame:
    days = (pd.to_datetime(frame["as_of_date"], utc=True)
            - pd.to_datetime(frame["first_purchase_at"], utc=True)).dt.days
    return frame.assign(tenure_band=pd.cut(
        days, [0, 365, 3 * 365, float("inf")], right=False, labels=TENURE_ORDER,
    ))


def cash_summary(frame: pd.DataFrame, groups: list[str]) -> pd.DataFrame:
    data = frame.assign(
        cash_buyer=frame["cash_purchase_count_60d"].gt(0),
        cash_usd=frame["cash_spent_usd_60d"].astype(float),
    )
    result = data.groupby(groups, observed=True, dropna=False).agg(
        players=("cash_buyer", "size"), cash_purchasers=("cash_buyer", "sum"),
        cash_usd=("cash_usd", "sum"),
    ).reset_index()
    result["cash_purchaser_share"] = result["cash_purchasers"] / result["players"]
    result["usd_per_player"] = result["cash_usd"] / result["players"]
    result["usd_per_purchaser"] = result["cash_usd"] / result["cash_purchasers"].where(result["cash_purchasers"].gt(0))
    return result


def audience_summary(frame: pd.DataFrame, dimension: str) -> pd.DataFrame:
    """One group per selected trait. Playtime uses relative score bands, never invented hours."""
    if dimension not in AUDIENCE_DIMENSIONS.values():
        raise ValueError("Unsupported audience dimension")
    data = with_tenure(frame) if dimension == "tenure_band" else frame.copy()
    if dimension == "playtime_band":
        if data["total_mastery_points"].nunique() <= 1:
            data[dimension] = "Similar playtime"
        else:
            codes = pd.qcut(data["total_mastery_points"], 5, labels=False, duplicates="drop")
            observed_codes = sorted(codes.dropna().unique())
            count = len(observed_codes)
            labels = (["Similar playtime"] if count == 1 else
                      [PLAYTIME_ORDER[round(index * 4 / (count - 1))] for index in range(count)])
            data[dimension] = pd.Categorical(
                codes.map(dict(zip(observed_codes, labels, strict=True))), categories=labels, ordered=True,
            )
    result = cash_summary(data, [dimension])
    result["audience"] = result[dimension].astype(str)
    return result


def experience_summary(frame: pd.DataFrame, bins: int = 8) -> pd.DataFrame:
    data = with_tenure(frame).dropna(subset=["total_mastery_points", "tenure_band"])
    data = data.loc[data["total_mastery_points"] > 0].copy()
    if data.empty:
        return pd.DataFrame()
    data["mastery_band"] = (0 if data["total_mastery_points"].nunique() == 1 else
                            pd.qcut(data["total_mastery_points"], bins, labels=False, duplicates="drop"))
    groups = ["tenure_band", "mastery_band"]
    result = cash_summary(data, groups)
    bounds = data.groupby(groups, observed=True).agg(
        mastery_points=("total_mastery_points", "median"),
        min_mastery=("total_mastery_points", "min"), max_mastery=("total_mastery_points", "max"),
    ).reset_index()
    return result.merge(bounds, on=groups, validate="one_to_one").sort_values(["tenure_band", "mastery_points"])


def cosmetic_summary(frame: pd.DataFrame, axis: str, dimension: str) -> pd.DataFrame:
    if dimension not in {"active_playstyle", "main_role", "tier"}:
        raise ValueError("Unsupported content audience dimension")
    data = frame.loc[frame["content_purchase_count_alltime"].gt(0)].dropna(
        subset=[axis, dimension, "cosmetic_bias_alltime"],
    ).copy()
    data["cosmetic_bias_alltime"] = data["cosmetic_bias_alltime"].astype(float)
    data["pool_band"] = pd.cut(data[axis], [index / 10 for index in range(11)], include_lowest=True, labels=False)
    return data.groupby([dimension, "pool_band"], observed=True).agg(
        pool_value=(axis, "median"), players=("cosmetic_bias_alltime", "size"),
        mean_cosmetic_share=("cosmetic_bias_alltime", "mean"),
        q1=("cosmetic_bias_alltime", lambda values: values.quantile(0.25)),
        q3=("cosmetic_bias_alltime", lambda values: values.quantile(0.75)),
        content_events=("content_purchase_count_alltime", "sum"),
    ).reset_index().sort_values([dimension, "pool_value"])


def discount_summary(frame: pd.DataFrame, dimension: str) -> pd.DataFrame:
    data = frame.loc[frame["cash_purchase_count_60d"].gt(0)].copy()
    counts = data["cash_discounted_purchase_count_60d"].astype(float)
    # Reconstruct discounted-fraction sums to weight the conditional mean by events,
    # rather than treating a one-event purchaser as equal to a many-event purchaser.
    data["discount_fraction_sum"] = data["cash_discount_mean_60d"].astype(float).fillna(0) * counts
    data["discounted_cash_buyer"] = counts.gt(0)
    result = data.groupby(dimension, observed=True).agg(
        cash_purchasers=("cash_purchase_count_60d", "size"),
        cash_events=("cash_purchase_count_60d", "sum"),
        discounted_cash_purchasers=("discounted_cash_buyer", "sum"),
        discounted_events=("cash_discounted_purchase_count_60d", "sum"),
        discount_fraction_sum=("discount_fraction_sum", "sum"),
    ).reset_index()
    result["cash_discount_share"] = result["discounted_events"] / result["cash_events"]
    result["cash_discount_mean"] = result["discount_fraction_sum"] / result["discounted_events"].where(result["discounted_events"].gt(0))
    return result
