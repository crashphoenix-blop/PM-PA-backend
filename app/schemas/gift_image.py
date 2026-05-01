from pydantic import BaseModel, ConfigDict


class GiftImageRead(BaseModel):
    url: str
    sort_order: int
    is_primary: bool

    model_config = ConfigDict(from_attributes=True)
