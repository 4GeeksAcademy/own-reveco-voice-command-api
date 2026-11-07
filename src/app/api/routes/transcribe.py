import re

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool
from groq import APIConnectionError, APIStatusError
from pydantic import ValidationError
from starlette.datastructures import UploadFile

from src.app.api.routes.tasks import create_task, delete_task, get_tasks, replace_task, update_task
from src.app.core.config import get_settings
from src.app.schemas.voice import (
    InstructionPayload,
    InstructionRequest,
    TaskCreate,
    TaskReplace,
    TaskUpdate,
    TranscribeFlowResponse,
)
from src.app.services.instruction import get_client, groq_error, resolve_instruction
from src.app.utils.language import normalize_transcription_language

router = APIRouter(tags=["transcribe"])


@router.get("/")
async def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/transcribe", response_model=TranscribeFlowResponse)
async def transcribe_and_run_flow(request: Request) -> TranscribeFlowResponse:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].lower()
    if content_type == "application/json":
        try:
            payload = InstructionRequest.model_validate(await request.json())
        except (ValueError, ValidationError):
            raise HTTPException(status_code=422, detail="Transcripción inválida") from None
        transcription = payload.transcription.strip()
    elif content_type == "multipart/form-data":
        async with request.form() as form:
            audio = form.get("file")
            if not isinstance(audio, UploadFile):
                raise HTTPException(status_code=422, detail="Se requiere un archivo de audio")
            language = normalize_transcription_language(form.get("language"))
            audio_bytes = await audio.read()
            if not audio_bytes:
                raise HTTPException(status_code=422, detail="El archivo de audio está vacío")
            transcription = await run_in_threadpool(
                transcribe_audio, audio.filename or "audio.webm", audio_bytes, language
            )
    else:
        raise HTTPException(status_code=415, detail="Tipo de contenido no compatible")

    if not transcription:
        raise HTTPException(status_code=422, detail="La transcripción está vacía")
    instruction = await run_in_threadpool(resolve_instruction, transcription)
    result = await run_in_threadpool(execute_instruction, instruction)
    return TranscribeFlowResponse(
        transcription=transcription, instruction=instruction, result=result
    )


def transcribe_audio(filename: str, audio: bytes, language: str | None) -> str:
    arguments = {
        "file": (filename, audio),
        "model": get_settings().groq_transcription_model,
    }
    if language:
        arguments["language"] = language
    try:
        response = get_client().audio.transcriptions.create(**arguments)
    except (APIConnectionError, APIStatusError) as error:
        raise groq_error(error) from None
    if not isinstance(response.text, str):
        raise HTTPException(status_code=502, detail="Groq devolvió una transcripción inválida")
    return response.text.strip()


def execute_instruction(instruction: InstructionPayload) -> object:
    method, endpoint, params = instruction.method, instruction.endpoint, instruction.params
    try:
        if endpoint == "/tasks" and method == "GET" and not params:
            return [task.model_dump() for task in get_tasks()]
        if endpoint == "/tasks" and method == "POST" and set(params) <= {"title", "done"}:
            return create_task(TaskCreate.model_validate(params)).model_dump()
        match = re.fullmatch(r"/tasks/([1-9][0-9]*)", endpoint)
        if match:
            task_id = int(match.group(1))
            if method == "PUT" and set(params) == {"title", "done"}:
                return replace_task(task_id, TaskReplace.model_validate(params)).model_dump()
            if method == "PATCH" and set(params) <= {"title", "done"}:
                return update_task(task_id, TaskUpdate.model_validate(params)).model_dump()
            if method == "DELETE" and not params:
                return delete_task(task_id)
    except ValidationError:
        pass
    raise HTTPException(status_code=502, detail="Groq devolvió una acción inválida")
