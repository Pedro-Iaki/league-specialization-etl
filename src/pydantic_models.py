from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class RiotPlayerEntry(BaseModel):
    model_config = ConfigDict(extra="ignore")  # ignore unexpected new fields

    queueType: str
    tier: str
    rank: str
    puuid: str
    leaguePoints: int = Field(ge=0)
    wins: int = Field(ge=0)
    losses: int = Field(ge=0)
    veteran: bool
    inactive: bool
    freshBlood: bool
    hotStreak: bool


class ChampionMasteryEntry(BaseModel):
    model_config = ConfigDict(extra="ignore")

    puuid: str
    championId: int
    championLevel: int = Field(ge=1)
    championPoints: int = Field(ge=0)
    lastPlayTime: int
    championPointsSinceLastLevel: int
    championPointsUntilNextLevel: int
    milestoneGrades: list = Field(default_factory=list)


class Tier(str, Enum):
    DIAMOND = "DIAMOND"
    EMERALD = "EMERALD"
    PLATINUM = "PLATINUM"
    GOLD = "GOLD"
    SILVER = "SILVER"
    BRONZE = "BRONZE"
    IRON = "IRON"


class Division(str, Enum):
    I = "I"
    II = "II"
    III = "III"
    IV = "IV"


class ExtractionConfigManifest(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True, str_strip_whitespace=True)

    api_key: str = Field(min_length=1)
    players_fetch_depth: int = Field(ge=1, le=1000)
    mastery_task_limit: int = Field(ge=1, le=1000)
    full_check: bool = False
    region: str = Field(min_length=1)
    queue: str = Field(min_length=1)
    tiers: list[Tier] = Field(default_factory=lambda: list(Tier), min_length=1)
    divisions: list[Division] = Field(default_factory=lambda: list(Division), min_length=1)
    freshness_threshold_minutes: int = Field(default=10080, ge=1)
    max_refresh_scale: float = Field(default=4, gt=0, allow_inf_nan=False)
    runs_per_load: int = Field(default=10, ge=1)
    pause_discovery_at_refresh_cap: bool = True
    ingest_job_id: int = Field(gt=0)
    ingestion_timeout_seconds: int = Field(default=900, gt=0)
    dbt_job_id: int = Field(gt=0)
    dbt_timeout_seconds: int = Field(default=1800, gt=0)
