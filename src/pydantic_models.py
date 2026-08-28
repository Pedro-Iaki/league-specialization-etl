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
    api_key: str
    version: str
    players_fetch_depth: int = Field(ge=1, le=1000)
    mastery_task_limit: int = Field(ge=1, le=1000)
    full_check: bool
    region: str
    queue: str
    tiers: list[Tier] = Field(default_factory=list)
    divisions: list[Division] = Field(default_factory=list)
