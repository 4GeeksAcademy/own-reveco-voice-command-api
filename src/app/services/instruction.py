import json

from fastapi import HTTPException, status
from groq import APIConnectionError, APIStatusError, APITimeoutError, BadRequestError, Groq
from pydantic import ValidationError

from src.app.api.routes.tasks import tasks, tasks_lock
from src.app.core.config import get_settings
from src.app.schemas.voice import InstructionPayload


SYSTEM_PROMPT = """Convierte la instrucción del usuario en una operación de tareas.
Responde SOLO con un objeto JSON con las claves endpoint, method y params.
Usa únicamente GET, POST, PUT, PATCH o DELETE y rutas /tasks o /tasks/{id}.
Para operaciones sobre una tarea, resuelve el id usando la lista proporcionada.
Para PUT incluye title y done; para PATCH incluye solo los campos que cambian.
No inventes tareas ni identificadores. Si no puedes resolver la petición, responde {}.
Ejemplos (las tareas indicadas son solo para ese ejemplo):
Usuario: "Añade comprar pan"; tareas: []
Respuesta: {"endpoint":"/tasks","method":"POST","params":{"title":"comprar pan"}}
Usuario: "List my tasks"; tareas: []
Respuesta: {"endpoint":"/tasks","method":"GET","params":{}}
Usuario: "Marca comprar pan como hecha"; tareas: [{"id":3,"title":"comprar pan"}]
Respuesta: {"endpoint":"/tasks/3","method":"PATCH","params":{"done":true}}
Usuario: "Rename buy milk to buy bread"; tareas: [{"id":4,"title":"buy milk"}]
Respuesta: {"endpoint":"/tasks/4","method":"PATCH","params":{"title":"buy bread"}}
Usuario: "Borra la segunda"; tareas: [{"id":2,"title":"pan"},{"id":7,"title":"leche"}]
Respuesta: {"endpoint":"/tasks/7","method":"DELETE","params":{}}
Usuario: "Replace the first task with call Ana, not done"; tareas: [{"id":5,"title":"call Bob"}]
Respuesta: {"endpoint":"/tasks/5","method":"PUT","params":{"title":"call Ana","done":false}}
Usuario: "Delete task 9"; tareas: [{"id":9,"title":"clean"}]
Respuesta: {"endpoint":"/tasks/9","method":"DELETE","params":{}}
Usuario: "Mostrar mis tareas"; tareas: []
Respuesta: {"endpoint":"/tasks","method":"GET","params":{}}"""


def get_client() -> Groq:
    settings = get_settings()
    return Groq(
        api_key=settings.groq_api_key,
        timeout=settings.request_timeout_seconds,
        max_retries=0,
    )


def groq_error(error: Exception) -> HTTPException:
    if isinstance(error, APITimeoutError):
        return HTTPException(status_code=504, detail="Groq agotó el tiempo de espera")
    if isinstance(error, APIStatusError) and error.status_code == 401:
        return HTTPException(status_code=502, detail="Error de autenticación con Groq")
    if isinstance(error, APIStatusError) and error.status_code == 429:
        return HTTPException(status_code=429, detail="Límite de solicitudes de Groq alcanzado")
    return HTTPException(status_code=502, detail="No se pudo completar la solicitud a Groq")


def resolve_instruction(transcription: str) -> InstructionPayload:
    settings = get_settings()
    with tasks_lock:
        current_tasks = [{"id": task["id"], "title": task["title"]} for task in tasks]
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(
            {"transcription": transcription, "tasks": current_tasks}, ensure_ascii=False
        )},
    ]
    try:
        client = get_client()
        try:
            response = client.chat.completions.create(
                model=settings.groq_model,
                messages=messages,
                temperature=0,
                response_format={"type": "json_object"},
            )
        except BadRequestError as error:
            message = str(error).lower()
            if "response_format" not in message or not any(
                phrase in message for phrase in ("not supported", "unsupported")
            ):
                raise
            response = client.chat.completions.create(
                model=settings.groq_model, messages=messages, temperature=0
            )
    except (APIConnectionError, APIStatusError) as error:
        raise groq_error(error) from None

    try:
        data = json.loads(response.choices[0].message.content)
        if not isinstance(data, dict) or set(data) != {"endpoint", "method", "params"}:
            raise ValueError
        instruction = InstructionPayload.model_validate(data)
        if instruction.method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
            raise ValueError
        if not instruction.endpoint.startswith("/tasks"):
            raise ValueError
        return instruction
    except (ValueError, TypeError, IndexError, AttributeError, ValidationError):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Groq devolvió una instrucción inválida",
        ) from None