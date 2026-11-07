from threading import RLock

from fastapi import APIRouter, HTTPException, status

from src.app.schemas.voice import Task, TaskCreate, TaskReplace, TaskUpdate

router = APIRouter(prefix="/tasks", tags=["tasks"])
tasks: list[dict] = []
next_id = 1
tasks_lock = RLock()


@router.get("", response_model=list[Task])
def get_tasks() -> list[Task]:
    with tasks_lock:
        return [Task.model_validate(task) for task in tasks]


@router.post("", response_model=Task, status_code=status.HTTP_201_CREATED)
def create_task(payload: TaskCreate) -> Task:
    global next_id
    with tasks_lock:
        task = {"id": next_id, **payload.model_dump()}
        next_id += 1
        tasks.append(task)
        return Task.model_validate(task)


@router.put("/{task_id}", response_model=Task)
def replace_task(
    task_id: int,
    payload: TaskReplace,
) -> Task:
    with tasks_lock:
        task = find_task(task_id)
        task.update(payload.model_dump())
        return Task.model_validate(task)


@router.patch("/{task_id}", response_model=Task)
def update_task(
    task_id: int,
    payload: TaskUpdate,
) -> Task:
    with tasks_lock:
        task = find_task(task_id)
        task.update(payload.model_dump(exclude_unset=True))
        return Task.model_validate(task)


@router.delete("/{task_id}")
def delete_task(task_id: int) -> dict[str, str]:
    with tasks_lock:
        tasks.remove(find_task(task_id))
        return {"message": "Tarea eliminada correctamente"}


def find_task(task_id: int) -> dict:
    for task in tasks:
        if task["id"] == task_id:
            return task
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Tarea no encontrada",
    )
