# Voice Command API

API del ejercicio de 4Geeks Academy para administrar tareas mediante texto o audio. Groq transcribe el audio e interpreta la instrucción; el backend ejecuta la operación solicitada.

## Requisitos

- Python 3.11 o superior, [uv](https://docs.astral.sh/uv/) y Node.js con npm.
- Una cuenta de Groq y una clave válida configurada localmente.

## Instalación y configuración

En la raíz del proyecto:

```bash
uv sync
cp .env.example .env
```

Edita `.env` y configura `GROQ_API_KEY` sin compartirla. Las demás opciones incluyen `GROQ_MODEL` (por defecto `llama-3.1-8b-instant`), `GROQ_TRANSCRIPTION_MODEL` (por defecto `whisper-large-v3-turbo`), `REQUEST_TIMEOUT_SECONDS` y `ALLOWED_ORIGINS` (separados por comas). La disponibilidad de modelos depende de Groq y de la cuenta.

Inicia el backend:

```bash
uv run uvicorn src.main:app --reload --host 0.0.0.0 --port 8000
```

La documentación interactiva está en `http://127.0.0.1:8000/docs`. En otra terminal inicia el frontend:

```bash
cd frontend
cp .env.example .env
npm install
npm run dev
```

El frontend usa `VITE_API_BASE_URL`, cuyo ejemplo apunta a `http://127.0.0.1:8000`. En Codespaces configura esa variable con la URL pública HTTPS del puerto 8000; el origen del puerto 5173 se añade automáticamente a CORS cuando Codespaces proporciona su nombre y dominio.

## Ejemplos de la API

Los siguientes comandos usan el backend local. En los ejemplos con ID, crea primero la tarea y sustituye `1` por su ID real cuando corresponda.

Estado:

```bash
curl http://127.0.0.1:8000/
```

Listar y crear tareas:

```bash
curl http://127.0.0.1:8000/tasks
curl -X POST http://127.0.0.1:8000/tasks -H 'Content-Type: application/json' -d '{"title":"comprar pan"}'
```

Reemplazar, modificar parcialmente y borrar una tarea:

```bash
curl -X PUT http://127.0.0.1:8000/tasks/1 -H 'Content-Type: application/json' -d '{"title":"comprar leche","done":false}'
curl -X PATCH http://127.0.0.1:8000/tasks/1 -H 'Content-Type: application/json' -d '{"done":true}'
curl -X DELETE http://127.0.0.1:8000/tasks/1
```

Interpretar una instrucción sin ejecutar la operación:

```bash
curl -X POST http://127.0.0.1:8000/instruction -H 'Content-Type: application/json' -d '{"transcription":"Añade comprar pan"}'
```

Otras frases: «Muestra mis tareas», «Marca comprar pan como hecha», «Renombra comprar pan a comprar leche», «Borra la segunda» y «Replace the first task with call Ana, not done». La resolución de nombres y posiciones utiliza las tareas existentes.

Interpretar y ejecutar texto, o transcribir y ejecutar audio:

```bash
curl -X POST http://127.0.0.1:8000/transcribe -H 'Content-Type: application/json' -d '{"transcription":"Añade comprar pan"}'
curl -X POST http://127.0.0.1:8000/transcribe -F 'file=@audio.webm' -F 'language=es'
```

En audio, `language` es opcional; al omitirlo se detecta automáticamente. Ambas variantes de `/transcribe` devuelven `transcription`, `instruction` y `result`. `/instruction` solo devuelve la instrucción interpretada y no modifica tareas.

## Pruebas y almacenamiento

```bash
uv run pytest
```

Las pruebas simulan Groq y no necesitan una clave real. Las tareas viven únicamente en memoria: se pierden al reiniciar el proceso y no se comparten entre varios procesos o trabajadores.