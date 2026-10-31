import time
import uvicorn
from fastapi import FastAPI, BackgroundTasks

app = FastAPI()

# 后台任务说的情况是:前端发一个请求,后端接口接收到请求后立即返回响应
# 但是接口当中调用了后台任务,后台任务可以在后台继续执行
# 接口返回已经姐说了,后台任务还在运行
# 所有的接口函数都不是程序调用的,而是fastapi框架调用的


def print_love(n,seconds=1):
    while n > 0:
        print("我爱你杨幂")
        time.sleep(seconds)
        n -= 1

@app.get("/backgroundtask")
def background_task(background_tasks : BackgroundTasks):
    background_tasks.add_task(print_love, 10,seconds=2) # 后面的10是任务函数的参数
    return {"message": "后台任务正在执行"}
