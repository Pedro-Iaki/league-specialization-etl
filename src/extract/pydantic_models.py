from typing import List, Optional
from pydantic import BaseModel, Field, ConfigDict

class RiotPlayerEntry(BaseModel):
    
    model_config = ConfigDict(extra="ignore")  # Ignore unexpected new fields from Riot

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


class NextSeasonMilestone(BaseModel):
    model_config = ConfigDict(extra="ignore")
    
    requireGradeCounts: dict
    rewardMarks: int
    bonus: bool
    totalGamesRequires: int


class ChampionMasteryEntry(BaseModel):
    model_config = ConfigDict(extra="ignore")

    puuid: str
    championId: int
    championLevel: int = Field(ge=1)
    championPoints: int = Field(ge=0)
    lastPlayTime: int
    championPointsSinceLastLevel: int
    championPointsUntilNextLevel: int
    markRequiredForNextLevel: int = None
    tokensEarned: int = None
    championSeasonMilestone: int = None
    milestoneGrades: List = Field(default_factory=list)
    nextSeasonMilestone: Optional[NextSeasonMilestone] = None