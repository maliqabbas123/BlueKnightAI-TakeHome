from dataclasses import dataclass
from typing import Protocol


@dataclass(slots=True)
class LLMMessage:
    role: str
    content: str


@dataclass(slots=True)
class LLMResponse:
    content: str
    input_tokens: int
    output_tokens: int


class LLMClient(Protocol):
    async def call(
        self,
        *,
        operation: str,
        request_id: str,
        messages: list[LLMMessage],
        model: str | None = None,
    ) -> LLMResponse: ...


class InMemoryLLMClient:
    def __init__(self) -> None:
        self.call_count = 0
        self.raise_next: Exception | None = None
        self.requests: list[dict[str, object]] = []

    async def call(
        self,
        *,
        operation: str,
        request_id: str,
        messages: list[LLMMessage],
        model: str | None = None,
    ) -> LLMResponse:
        self.call_count += 1
        self.requests.append(
            {"operation": operation, "request_id": request_id, "messages": messages, "model": model}
        )
        if self.raise_next is not None:
            exc = self.raise_next
            self.raise_next = None
            raise exc
        last_user = next((message.content for message in reversed(messages) if message.role == "user"), "")
        content = last_user.upper()
        return LLMResponse(
            content=content,
            input_tokens=len(last_user.split()),
            output_tokens=len(content.split()),
        )


llm_client = InMemoryLLMClient()

