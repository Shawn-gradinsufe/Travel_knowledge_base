import uvicorn
from fastapi import FastAPI

app = FastAPI(
    title="FastAPI",
    description="这是一个测试的接口服务",
    version="0.1.0"
)
# 这些参数后期在接口文档中就可以看到，fastapi会给我们自动生成在线接口文档
# 接口文档:接口说明，主要是后端人员把每个接口的使用说明给前端

# 接口就是一个函数
# 服务器起来但是没有接口，就是一个空壳子，可以访问，但没有东西

@app.get("/") # 一旦使用路由函数，这个函数就变成了路由函数
def index():
    return {"message": "我爱你杨幂"}
    # 这里返回的实际是一个json，只是他是简写实际写的全是：
    # return JsonResponse(content={"message": "我爱你杨幂"})
    # 这里的JsonResponse是fastapi给我们封装好的，可以直接返回json格式的响应体
# 对于任何一个网址，实际最后面都默认有一个"/"

# 是fastapi从url中解析路径吗？，看谁的路由和写的路径可以对应上，对应上了就调用路由函数。发送请求的是什么？

# fastapi的使用流程:
# 1、写路径
# 2、写函数
# 3、返回




if __name__ == '__main__':
    uvicorn.run(app, # 传入一个ASGI应用对象，这里是我们的FastAPI实例
                host="0.0.0.0", # 允许所有用户访问
                port=8000)
    # 启动一个ASGI服务器，默认使用的是uvicorn
    # uvicorn.run() 底层用的是uvloop, 异步IO库
