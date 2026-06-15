from pydantic import BaseModel
from typing import List
from app.schemas.gift import GiftRead


class AIQuestionnaireRequest(BaseModel):
    recipient: str
    occasion: str
    budget: str
    style: str


class AIRecommendResponse(BaseModel):
    gifts: List[GiftRead]
