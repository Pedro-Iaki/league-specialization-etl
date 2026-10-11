"""Editable fictional assumptions; these relationships are imposed, not discovered."""

GENERATOR_VERSION = "1.2"
CUSTOMER_PROBABILITIES = {"sardine": 0.72, "dolphin": 0.24, "whale": 0.04}
BASE_WEIGHTS = {
    "payment_consistency": 0.55,
    "payment_frequency": 0.22,  # fraction of tenure calendar months with cash purchases
    "payment_intensity": 1.3,  # expected cash transactions per purchasing month
    "cosmetic_bias": 0.45,  # cosmetics / (cosmetics + champion unlocks), by event count
    "owned_champions": 12,  # extra ownership above a noisy mastery-count anchor
    "discount_share": 0.18,
    "discount_mean": 0.25,  # conditional on a discounted event
}

# Unlisted primary champion keys use a neutral default; incomplete real profiles are excluded.
# Entropy means champion-pool diversity, never consistency of gameplay activity.
WEIGHT_OFFSETS = {
    "tier": {
        "default": {},
        "IRON": {"payment_frequency": -0.06},
        "BRONZE": {"payment_frequency": -0.04},
        "GOLD": {"payment_intensity": 0.1},
        "PLATINUM": {"payment_frequency": 0.02},
        "EMERALD": {"payment_frequency": 0.04},
        "DIAMOND": {"payment_frequency": 0.06, "payment_consistency": 0.08},
        "MASTER": {"payment_frequency": 0.08, "payment_consistency": 0.1},
        "GRANDMASTER": {"payment_frequency": 0.08},
        "CHALLENGER": {"payment_frequency": 0.08},
    },
    "main_role": {
        "default": {},
        "Middle": {"cosmetic_bias": 0.08},
        "Bottom": {"cosmetic_bias": 0.05},
        "Support": {"discount_share": 0.06},
        "Jungle": {"owned_champions": 5},
        "Top": {"payment_consistency": 0.03},
    },
    "primary_champion": {
        "default": {},
        "103": {"cosmetic_bias": 0.12},  # Ahri
        "157": {"cosmetic_bias": 0.10},  # Yasuo
        "81": {"cosmetic_bias": 0.08},  # Ezreal
    },
    "active_playstyle": {
        "default": {},
        "specialist": {"cosmetic_bias": 0.10, "owned_champions": -5},
        "multispecialist": {"cosmetic_bias": 0.04},
        "versatile": {"owned_champions": 5},
        "generalist": {"owned_champions": 10, "cosmetic_bias": -0.06},
    },
    "account_age": {
        "default": {},
        "new": {"owned_champions": -5, "payment_frequency": -0.04},
        "established": {},
        "veteran": {"owned_champions": 8, "payment_consistency": 0.06},
    },
    "mastery_sum": {
        "default": {},
        "low": {"payment_intensity": -0.2},
        "medium": {},
        "high": {"payment_intensity": 0.3, "owned_champions": 6},
    },
    "ranked_share": {
        "default": {},
        "low": {"cosmetic_bias": 0.05},
        "medium": {},
        "high": {"payment_consistency": 0.06},
    },
    "top1_champion_share": {
        "default": {},
        "low": {"owned_champions": 4},
        "medium": {},
        "high": {"cosmetic_bias": 0.07},
    },
    "active_entropy": {
        "default": {},
        "low": {"cosmetic_bias": 0.04},
        "medium": {},
        "high": {"owned_champions": 5},
    },
    "customer_type": {
        "default": {},
        "sardine": {"payment_frequency": -0.10, "payment_intensity": -0.4},
        "dolphin": {"payment_frequency": 0.12, "payment_intensity": 0.7},
        "whale": {"payment_frequency": 0.40, "payment_intensity": 3.0, "cosmetic_bias": 0.12},
    },
}

CONTROL_BOUNDS = {
    "payment_consistency": (0, 1), "payment_frequency": (0, 1),
    "payment_intensity": (0.2, 8), "cosmetic_bias": (0, 0.85),
    "owned_champions": (0, 60), "discount_share": (0, 1), "discount_mean": (0, 0.8),
}
