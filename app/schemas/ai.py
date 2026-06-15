from pydantic import BaseModel
from typing import List
from app.schemas.gift import GiftRead


class AIQuestionnaireRequest(BaseModel):
    recipient: str
    occasion: str
    budget: str
    style: str
    is_urgent: bool = False
    age_group: str = ""
    interests: str = ""


class AIRecommendResponse(BaseModel):
    gifts: List[GiftRead]
    budget_expanded: bool = False
