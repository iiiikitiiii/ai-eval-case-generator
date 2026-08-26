from pydantic import BaseModel


class LlmProviderOut(BaseModel):
    provider: str
    options: list[str]


class LlmProviderIn(BaseModel):
    provider: str
