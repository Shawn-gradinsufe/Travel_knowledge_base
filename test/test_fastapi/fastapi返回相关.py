# 返回说的是返回响应,主要目前返回的就是1.json 2.文件 3.流式输出
import pathlib

import uvicorn
from fastapi import FastAPI
from starlette.responses import JSONResponse, FileResponse
from starlette.staticfiles import StaticFiles

app = FastAPI()









# todo 一.返回json
# 返回json,我们只需要return后面跟上一个python数据即可,一般都是字典或者对象,或者是字典列表,对象列表
# fastapi会自动把我们return的结果作为JsonResponse的content,并且帮我们做序列化设置正确content_type
# 后期返回数据直接写返回的数据即可,不需要写JSONResponse,它属于复杂写法,我们只需要写简写
@app.get("/returnjson")
def returnjson():
    # return {"hello": "world"}
    return JSONResponse(
        content = {"hello": "world"},
        status_code = 200,
        media_type="application/json"
    )

# todo 二.返回文件
# 请求头是前端要给后端传递某些特殊信息的时候,放在请求头传递给后端
# 响应头是后端返回给前端浏览器的,浏览器在看到这些响应头信息的时候,就知道做对应的什么处理
# 响应头是我们让浏览器根据我们的指令去做一些事
@app.get("/download")
async def download():
    return FileResponse(
        path=r"",
        media_type="image/png",
        # 下面这个响应头信息就是告诉浏览器对图片进行下载
        headers = {"Content-Disposition": "attachment; filename=mylove03.png"}
    )


# todo 三.返回HTML 了解
from fastapi.responses import HTMLResponse
@app.get("/hello")
async def hello(name: str = "游客"):
    html_content = f"""
    <html>
        <body>
            <h1>你好，{name}！</h1>     # <h1>到<h6>是网页的标题标签,<h1>最大
        </body>
    </html>
    """
    return HTMLResponse(content=html_content, status_code=200)


# todo 四.返回纯文本 了解
from fastapi.responses import PlainTextResponse
@app.get("/text")
async def get_text():
    return PlainTextResponse(content="这是纯文本响应", status_code=200)


# todo 五.返回重定向 了解
from fastapi.responses import RedirectResponse

@app.get("/old-path")
async def redirect_old_path():
    # 重定向到 /new-path，状态码 307 表示临时重定向
    return RedirectResponse(url="/new-path", status_code=307)

@app.get("/new-path")
async def new_path():
    return {"message": "这是新接口"}



# todo 六.返回任意类型响应 Response
from fastapi.responses import Response

@app.get("/custom")
async def custom_response():
    # 返回二进制数据，指定自定义 MIME 类型
    return Response(
        content="<h1>纯文本</h1>",
        # media_type="text/plain",
        media_type="text/html",
        status_code=200)





if __name__ == '__main__':
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8000,
    )