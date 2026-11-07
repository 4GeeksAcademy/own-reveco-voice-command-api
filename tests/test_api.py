import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi.testclient import TestClient
from groq import APITimeoutError, AuthenticationError, RateLimitError

from src.app.api.routes import tasks as task_routes
from src.app.core.config import Settings


@pytest.fixture
def api(monkeypatch):
    settings = Settings(groq_api_key="", _env_file=None)
    monkeypatch.setattr("src.app.core.config.get_settings", lambda: settings)
    monkeypatch.setattr("src.app.services.instruction.get_settings", lambda: settings)
    monkeypatch.setattr("src.app.api.routes.transcribe.get_settings", lambda: settings)
    monkeypatch.setenv("CODESPACE_NAME", "example-space")
    monkeypatch.setenv("GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN", "example.dev")
    from src.app import main

    monkeypatch.setattr(main, "get_settings", lambda: settings)
    task_routes.tasks.clear()
    monkeypatch.setattr(task_routes, "next_id", 1)
    groq = MagicMock()
    monkeypatch.setattr("src.app.services.instruction.get_client", lambda: groq)
    monkeypatch.setattr("src.app.api.routes.transcribe.get_client", lambda: groq)
    with TestClient(main.create_app()) as client:
        yield client, groq
    task_routes.tasks.clear()


def completion(content):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def set_instruction(groq, endpoint="/tasks", method="GET", params=None):
    payload = {"endpoint": endpoint, "method": method, "params": params or {}}
    groq.chat.completions.create.return_value = completion(json.dumps(payload))


def test_instruction_uses_task_context_without_executing(api):
    client, groq = api
    client.post("/tasks", json={"title": "comprar pan"})
    set_instruction(groq, "/tasks/1", "PATCH", {"done": True})
    response = client.post("/instruction", json={"transcription": "marca comprar pan como hecha"})
    assert response.status_code == 200
    assert response.json() == {"endpoint": "/tasks/1", "method": "PATCH", "params": {"done": True}}
    request = groq.chat.completions.create.call_args.kwargs
    assert request["temperature"] == 0
    assert request["response_format"] == {"type": "json_object"}
    assert json.loads(request["messages"][1]["content"])["tasks"] == [
        {"id": 1, "title": "comprar pan"}
    ]
    assert client.get("/tasks").json()[0]["done"] is False


@pytest.mark.parametrize("content", [
    "{not-json}",
    "texto libre",
    '{"endpoint":"/tasks","method":"OTHER","params":{}}',
    '{"endpoint":"/other","method":"GET","params":{}}',
    '{"endpoint":"/tasks","method":"GET","params":[]}',
    '{"endpoint":"/tasks","method":"GET"}',
])
def test_instruction_rejects_invalid_output(api, content):
    client, groq = api
    groq.chat.completions.create.return_value = completion(content)
    response = client.post("/instruction", json={"transcription": "lista"})
    assert response.status_code == 502
    assert response.json() == {"detail": "Groq devolvió una instrucción inválida"}


@pytest.mark.parametrize("error_type, upstream_status, expected", [
    (AuthenticationError, 401, 502),
    (RateLimitError, 429, 429),
])
def test_controlled_groq_errors(api, error_type, upstream_status, expected):
    client, groq = api
    request = httpx.Request("POST", "https://example.invalid")
    response = httpx.Response(upstream_status, request=request)
    groq.chat.completions.create.side_effect = error_type("información sensible", response=response, body=None)
    result = client.post("/instruction", json={"transcription": "lista"})
    assert result.status_code == expected
    assert "información sensible" not in result.text


def test_groq_timeout(api):
    client, groq = api
    groq.chat.completions.create.side_effect = APITimeoutError(httpx.Request("POST", "https://example.invalid"))
    assert client.post("/instruction", json={"transcription": "lista"}).status_code == 504


def test_transcribe_text_executes_same_store(api):
    client, groq = api
    set_instruction(groq, "/tasks", "POST", {"title": "comprar pan"})
    response = client.post("/transcribe", json={"transcription": "Añade comprar pan"})
    assert response.status_code == 200
    assert response.json() == {
        "transcription": "Añade comprar pan",
        "instruction": {"endpoint": "/tasks", "method": "POST", "params": {"title": "comprar pan"}},
        "result": {"id": 1, "title": "comprar pan", "done": False},
    }
    assert client.get("/tasks").json() == [response.json()["result"]]
    groq.audio.transcriptions.create.assert_not_called()


def test_transcribe_audio_uses_language_and_executes(api):
    client, groq = api
    groq.audio.transcriptions.create.return_value = SimpleNamespace(text=" Lista mis tareas ")
    set_instruction(groq)
    response = client.post(
        "/transcribe",
        files={"file": ("command.webm", b"audio simulado", "audio/webm")},
        data={"language": "es"},
    )
    assert response.status_code == 200
    assert response.json()["transcription"] == "Lista mis tareas"
    assert response.json()["result"] == []
    assert groq.audio.transcriptions.create.call_args.kwargs["language"] == "es"
    assert groq.audio.transcriptions.create.call_args.kwargs["model"] == "whisper-large-v3-turbo"


@pytest.mark.parametrize("method, params, expected", [
    ("PATCH", {"done": True}, {"id": 1, "title": "pan", "done": True}),
    ("PUT", {"title": "leche", "done": False}, {"id": 1, "title": "leche", "done": False}),
    ("DELETE", {}, {"message": "Tarea eliminada correctamente"}),
])
def test_transcribe_dispatches_task_changes(api, method, params, expected):
    client, groq = api
    client.post("/tasks", json={"title": "pan"})
    set_instruction(groq, "/tasks/1", method, params)
    response = client.post("/transcribe", json={"transcription": "modifica la tarea"})
    assert response.status_code == 200
    assert response.json()["result"] == expected
    assert client.get("/tasks").json() == ([] if method == "DELETE" else [expected])


@pytest.mark.parametrize("endpoint, method, params", [
    ("/tasks/1/other", "DELETE", {}),
    ("/tasks-evil", "GET", {}),
    ("/tasks", "POST", {"title": " "}),
    ("/tasks/1", "PATCH", {}),
])
def test_transcribe_rejects_unsafe_actions(api, endpoint, method, params):
    client, groq = api
    set_instruction(groq, endpoint, method, params)
    assert client.post("/transcribe", json={"transcription": "prueba"}).status_code == 502
    assert client.get("/tasks").json() == []


def test_crud_and_ids(api):
    client, _ = api
    assert client.post("/tasks", json={"title": " "}).status_code == 422
    assert client.post("/tasks", json={"title": "pan"}).json()["id"] == 1
    assert client.patch("/tasks/1", json={"done": True}).json()["done"] is True
    assert client.put("/tasks/1", json={"title": "leche", "done": False}).json()["title"] == "leche"
    assert client.delete("/tasks/1").status_code == 200
    assert client.delete("/tasks/1").status_code == 404
    assert client.post("/tasks", json={"title": "agua"}).json()["id"] == 2


def test_codespaces_cors(api):
    client, _ = api
    origin = "https://example-space-5173.example.dev"
    response = client.options("/transcribe", headers={
        "Origin": origin, "Access-Control-Request-Method": "POST"
    })
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin