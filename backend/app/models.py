from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    field_validator,
    model_serializer,
    model_validator,
)


class ChatRequest(BaseModel):
    model_config = ConfigDict(strict=True)

    session_id: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=4000)
    system_prompt: str | None = None

    @field_validator("message", mode="before")
    @classmethod
    def trim_message(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("session_id")
    @classmethod
    def reject_blank_session(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("session_id must not be blank")
        return value


class ReplyMetadata(BaseModel):
    model_config = ConfigDict(strict=True)

    resolution_source: Literal["LIVE_INFERENCE", "LLM_CACHE"]
    model: str = Field(min_length=1)
    latency_ms: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    key_id: Annotated[str, Field(pattern=r"^key_[1-9]\d*$")] | None
    fallback_attempts: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_resolution(self) -> "ReplyMetadata":
        if self.resolution_source == "LLM_CACHE":
            if self.key_id is not None or self.fallback_attempts != 0:
                raise ValueError("Cached replies require a null key ID and zero fallbacks")
        elif self.key_id is None:
            raise ValueError("Live replies require the successful key ID")
        return self


class ChatResponse(BaseModel):
    model_config = ConfigDict(strict=True)

    session_id: str
    reply: str = Field(min_length=1)
    metadata: ReplyMetadata

    @field_validator("reply")
    @classmethod
    def reject_blank_reply(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("reply must not be blank")
        return value


class StoredMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    metadata: ReplyMetadata | None = None

    @model_serializer(mode="wrap")
    def serialize_message(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        value = handler(self)
        # Omit user metadata without stripping a cached assistant's required null key_id.
        if self.metadata is None:
            value.pop("metadata", None)
        return value


class HistoryResponse(BaseModel):
    session_id: str
    messages: list[StoredMessage]


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    keys_configured: int
    cache_enabled: bool
