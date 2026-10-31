import shutil
import time
import uuid
from datetime import datetime
from pathlib import Path

import uvicorn
from fastapi import BackgroundTasks, FastAPI, File, UploadFile
from fastapi import Path as Fpath
from pydantic import BaseModel, Field
from starlette.middleware.cors import CORSMiddleware

from atguigu.config.config import TourismConfig
from atguigu.import_process.main_graph import MainGraphRunner, iter_corpus_files
from atguigu.tool.filter_builder import count_rows
from atguigu.tool.logger import logger
from atguigu.tool.task_utils import (
    TASK_STATUS_COMPLETED,
    TASK_STATUS_FAILED,
    TASK_STATUS_PROCESSING,
    add_done_task,
    add_node_duration,
    add_running_task,
    get_task_info,
    update_task_status,
)

app = FastAPI(title="旅游知识库 - 导入服务")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = Path(r"E:\Python_projects\output\tourism")


def run_main_graph(task_id: str, local_dir: str, local_file_path: str):
    """后台执行单文档导入。"""
    try:
        update_task_status(task_id, TASK_STATUS_PROCESSING)
        MainGraphRunner.create_and_run({
            "task_id": task_id,
            "local_dir": local_dir,
            "local_file_path": local_file_path,
        })
        update_task_status(task_id, TASK_STATUS_COMPLETED)
    except Exception as e:
        logger.error(f"导入失败 {local_file_path}: {e}")
        update_task_status(task_id, TASK_STATUS_FAILED)


@app.post("/upload")
def upload(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    """上传单个 md/pdf 文件并异步导入。"""
    task_id = str(uuid.uuid4())
    add_running_task(task_id, "upload_file")
    start_time = time.time()

    local_dir = UPLOAD_DIR / datetime.now().strftime("%Y%m%d")
    local_dir.mkdir(parents=True, exist_ok=True)
    local_file_path = local_dir / file.filename

    with open(local_file_path, "wb") as f:
        shutil.copyfileobj(file.file, f, 1024 * 1024)

    add_done_task(task_id, "upload_file")
    add_node_duration(task_id, "upload_file", time.time() - start_time)

    background_tasks.add_task(run_main_graph, task_id, str(local_dir), str(local_file_path))
    return {"task_id": task_id, "file": file.filename}


class DirImportParams(BaseModel):
    data_root: str | None = Field(default=None, description="语料根目录，不传则用 .env 里的 TOUR_DATA_ROOT")


@app.post("/import_dir")
def import_dir(background_tasks: BackgroundTasks, params: DirImportParams | None = None):
    """
    批量导入整个语料目录。

    单文件失败不会中断整批（对应需求里「避免导入失败导致服务整体不可用」），
    失败的清单可以在 /status/{task_id} 的 failed 字段里看到。
    """
    task_id = str(uuid.uuid4())
    data_root = (params.data_root if params else None) or TourismConfig.data_root

    try:
        files = iter_corpus_files(data_root)
    except FileNotFoundError as e:
        return {"error": str(e)}

    def _run():
        update_task_status(task_id, TASK_STATUS_PROCESSING)
        runner = MainGraphRunner()
        failed = []
        for idx, path in enumerate(files, start=1):
            try:
                add_running_task(task_id, f"导入 {path.name}")
                runner.run({
                    "task_id": task_id,
                    "local_file_path": str(path),
                    "local_dir": str(path.parent),
                })
                add_done_task(task_id, f"导入 {path.name}")
            except Exception as e:
                logger.error(f"导入失败 {path.name}: {e}")
                failed.append({"file": path.name, "error": str(e)})
                add_done_task(task_id, f"导入 {path.name}")
        update_task_status(task_id, TASK_STATUS_COMPLETED if not failed else TASK_STATUS_FAILED)

    background_tasks.add_task(_run)
    return {"task_id": task_id, "total": len(files)}


@app.get("/status/{task_id}")
def get_task_status(task_id: str = Fpath(..., description="任务ID")):
    return get_task_info(task_id)


@app.get("/stats")
def stats():
    """知识库概览：切片数、实体数。"""
    return {
        "chunks": count_rows(TourismConfig.chunks_collection),
        "entities": count_rows(TourismConfig.entities_collection),
        "data_root": TourismConfig.data_root,
    }


if __name__ == '__main__':
    uvicorn.run(app, host="0.0.0.0", port=8000)
