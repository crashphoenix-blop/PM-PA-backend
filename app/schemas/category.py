from pydantic import BaseModel, ConfigDict


class CategoryRead(BaseModel):
    id: int
    name: str

    model_config = ConfigDict(from_attributes=True)
