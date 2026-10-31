import json
import queue
import time
import uuid

from fastapi import BackgroundTasks, Body, FastAPI, Path
from pydantic import BaseModel, Field
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import StreamingResponse

from atguigu.query_process.main_graph import QueryMainGraphRunner
from atguigu.tool.logger import logger
from atguigu.tool.mongo_tool import clear_history, get_recent_messages
from atguigu.tool.task_utils import (
    TASK_STATUS_COMPLETED,
    TASK_STATUS_FAILED,
    TASK_STATUS_PROCESSING,
    create_queue,
    get_data,
    get_task_info,
    put_data,
    remove_queue,
    update_task_status,
)

app = FastAPI(title="旅游知识库 - 查询服务")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# SSE 空闲超时：超过这个时间没有新事件就主动结束，避免连接永久挂着
SSE_IDLE_TIMEOUT = 180


@app.get("/health")
def health():
    return {"status": "ok", "service": "tourism-query"}


@app.get("/history/{session_id}")
def get_history(session_id: str = Path(..., description="会话id")):
    history_list = get_recent_messages(session_id, n=50)
    history_list = [{**item, "_id": str(item.get("_id"))} for item in history_list]
    history_list.sort(key=lambda item: item["ts"])
    return {"items": history_list}


@app.delete("/history/{session_id}")
def delete_history(session_id: str = Path(..., description="会话id")):
    clear_history(session_id)
    return {"message": "ok"}


class BodyParams(BaseModel):
    query: str = Field(..., description="用户问题")
    session_id: str = Field(..., description="会话id")


def run_main_graph(query: str, session_id: str, task_id: str):
    init_state = {
        "task_id": task_id,
        "session_id": session_id,
        "original_query": query,
    }
    try:
        update_task_status(task_id, TASK_STATUS_PROCESSING)
        put_data(task_id, event="progress", data=get_task_info(task_id))
        QueryMainGraphRunner.create_and_run(init_state)
        update_task_status(task_id, TASK_STATUS_COMPLETED)
        put_data(task_id, event="progress", data=get_task_info(task_id))
    except Exception as e:
        logger.error(f"查询失败: {e}")
        update_task_status(task_id, TASK_STATUS_FAILED)
        put_data(task_id, event="error", data={"error": str(e), **get_task_info(task_id)})


@app.post("/query")
def query(background_tasks: BackgroundTasks, body_params: BodyParams = Body(...)):
    task_id = str(uuid.uuid4())
    create_queue(task_id)
    background_tasks.add_task(run_main_graph, body_params.query, body_params.session_id, task_id)
    return {"task_id": task_id}


def generate_data(task_id: str):
    """
    SSE 事件生成器。

    原实现是 `while True: yield`，既没有终止条件也没有心跳：
    客户端断开后协程会一直挂着，任务失败时连接也不会关闭。
    这里改成收到 final / error 事件即结束，并加空闲超时兜底。
    """
    last_active = time.time()
    try:
        while True:
            try:
                data = get_data(task_id, timeout=5)
            except queue.Empty:
                if time.time() - last_active > SSE_IDLE_TIMEOUT:
                    yield "event: error\n"
                    yield 'data: {"error": "服务端等待超时"}\n\n'
                    return
                # 心跳注释行，防止中间代理把空闲连接掐掉
                yield ": keep-alive\n\n"
                continue

            last_active = time.time()
            event = data.get("event")
            yield f"event: {event}\n"
            yield f"data: {json.dumps(data.get('data'), ensure_ascii=False)}\n\n"

            if event in ("final", "error"):
                return
    finally:
        # 客户端断开时生成器会被关闭，这里兜底清理队列，避免内存泄漏
        remove_queue(task_id)


@app.get("/stream/{task_id}")
def stream_task(task_id: str = Path(..., description="任务id")):
    return StreamingResponse(
        generate_data(task_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


if __name__ == '__main__':
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8001)
