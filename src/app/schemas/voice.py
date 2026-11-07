from typing import Any

from pydantic import BaseModel, Field, StringConstraints, model_validator
from typing import Annotated


TaskTitle = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class TaskCreate(BaseModel):
    title: TaskTitle
    done: bool = False


class TaskReplace(BaseModel):
    title: TaskTitle
    done: bool


class TaskUpdate(BaseModel):
    title: TaskTitle | None = None
    done: bool | None = None

    @model_validator(mode="after")
    def validate_changes(self) -> "TaskUpdate":
        if not self.model_fields_set or any(
            getattr(self, field) is None for field in self.model_fields_set
        ):
            raise ValueError("Debe indicar al menos un campo no nulo")
        return self


class Task(BaseModel):
    id: int
    title: str
    done: bool


class InstructionRequest(BaseModel):
    transcription: str = Field(..., min_length=1)


class InstructionPayload(BaseModel):
    endpoint: str = Field(..., min_length=1)
    method: str = Field(..., min_length=1)
    params: dict[str, Any] = Field(default_factory=dict)


class TranscribeFlowResponse(BaseModel):
    transcription: str = Field(..., min_length=1)
    instruction: InstructionPayload
    result: Any
