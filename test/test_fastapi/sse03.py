"""
目标: 后端先接收查询请求,后台处理SSE推送处理结果

案例2:使用post请求加异步操作
1.前端发请求传递一个query,再传递一个session_id,两个参数到后端进行请求体接收
"""
import asyncio
import time

import uvicorn
from fastapi import FastAPI, Query, BackgroundTasks, Body
from pydantic import Field, BaseModel
from starlette.middleware.cors import CORSMiddleware
from asyncio import Queue

from starlette.responses import StreamingResponse

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # *代表允许所有域名访问
    allow_credentials=True, # 允许跨域请求携带凭证cookie
    allow_methods=["*"], # 允许跨域请求使用的HTTP方法
    allow_headers=["*"], # 允许跨域请求携带的头信息
)

class BodyParams(BaseModel):
    query:str = Field(...,description="查询内容")
    session_id:str = Field(...,description="会话ID")

q_dict = {}
async def make_data(query,session_id):
    if q_dict.get(session_id) is None:
        q_dict[session_id] = Queue()

    q = q_dict.get(session_id)
    await q.put("我爱杨幂01")
    await q.put("我爱杨幂02")
    await q.put("我爱杨幂03")
    await q.put("我爱杨幂04")
    await q.put("我爱杨幂05")
    await q.put(None)
# 后台任务当中其实是可以跑异步操作的,但是不建议,一旦后台任务中是异步操作,那么后台任务里面从高到低必须都是异步;后台任务本身就是一个异步的动作


@app.post("/sse03")
def sse03(
    background_tasks : BackgroundTasks,
    body_params:BodyParams = Body(...,description="请求体参数")
):
    query = body_params.query
    session_id = body_params.session_id

    background_tasks.add_task(make_data,query,session_id)

    return {"msg":"收到"}

@app.get("/handlersse03")
def handlersse03(
    session_id:str = Query(...,description="会话ID")
):
    async def generate_data():
        while q_dict.get(session_id) is None:
            # time.sleep(1)
            await asyncio.sleep(1)

        q = q_dict.get(session_id)
        while True:
            try:
                data = await q.get()
                await asyncio.sleep(1)
                yield f"event: {data.get("event")}\n"
                yield f"data: {data.get("data")}\n\n"

                a = 10/0
                if data.get("event") == "final":
                    break # 这里的break的作用是什么？
            except Exception as e:
                yield f"event: error\n"
                yield f"data: {e}\n\n"



    return StreamingResponse(generate_data(session_id),media_type="text/event-stream")

if __name__ == '__main__':
    uvicorn.run(app, host="0.0.0.0", port=8000)