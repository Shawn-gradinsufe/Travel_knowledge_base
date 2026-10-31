# 路径参数是前端在发请求的时候把参数写在路径的后面，http://www.baidu.com/index/1/yangmi
# baidu是域名,用域名替换了     /index是路径 /1/yangmi 是路径参数
# 请求方式 一般我们关注四种：get post put delete
# get和delete请求一般没有请求体
# post和put请求一般有请求体
# 前端一般在发送请求的时候，分为两大类：1、普通请求 2、ajax请求
# 普通请求一般只有get和post请求    浏览器地址栏输入回车(get请求) 或者 点击页面的链接a标签跳转(get请求) 或者 表单提交(post请求)
# ajax请求 就是通过js代码发起的请求 一般4种都有，现在我们前端基本发的都是ajax请求
# 普通请求发送请求的时候浏览器页面会刷新页面,ajax请求不会刷新页面
import pathlib
import shutil
import uuid

import uvicorn
from fastapi import FastAPI, Path, Query, Body, Depends, UploadFile, File
from starlette.requests import Request


app=FastAPI()


# todo 一、接收路径参数
@app.get("/testpath/{id}/{name}") # 路径参数占位，路径参数是属于路径的一部分
def testpath(
        id:int = Path(...,description="用户id", gt=0,le=100), # ... 代表必传,gt是大于，le是小于等于,Path等于是对路径参数的说明
        name:str = Path(...,description="用户名称",min_length=2)
):
    return {"id": id, "name": name}
# 后期fastapi拿到前端的路径后要做对比匹配，参数也得参与
# http发送过来的就是一坨报文字符串，fastapi进行的解析
# 任何参数考虑三个点：
# 1、前端怎么传
# 2、后端怎么接收
# 3、后端怎么校验
# 一旦传递路径参数，那么前后都必须传，不能可传可不传，否则就不是参数了
# 参数一般都要做校验



# todo 二、接收查询参数
@app.get("/testquery")
def testquery(
        id:int,
        # name:str = "haha" # 默认值可以写，代表前端可传可不传，如果要写默认值，默认值也是在校验当中去写
        name:str = Query(default="yangmi", description="用户名称", min_length=2), # 校验的时候去写默认值
        age:int = Query(...,description="用户年龄",gt=0,le=100) # 和Path的写法一模一样，
):
    return {"id": id, "name": name, "age": age}
# 1、前端怎么传：在url路径后面以？分割，k=v&k=v的形式传递，例如：http://www.baidu.com/index?id=1&name=yangmi，查询参数不占用路径的位置
# 2、后端怎么接收：直接在形参当中写即可，形参名字要和前端传递的k一致
# 3、后端怎么校验：Query(...) default和...是互斥的,二者只能选其一





# todo 三、接收请求体参数 一般都是传递json格式，还有表单类型(也属于请求体类型，让用户页面输入或者上传文件用的多，
#  例如网页上注册账号提交的信息，网申填简历信息)

# 这里就不能用get请求 我们就没办法用浏览器去做测试了，浏览器输入回车是普通的get请求
# 请求体参数要么post要么put
# 1、前端怎么传
# 2、后端怎么接收
# 3、后端怎么校验：分两层考虑，一、请求体参数使用Body，二、请求体当中的键使用pydantic来做校验

# pydantic就是为了限定请求体中的键

from pydantic import BaseModel, Field


class User(BaseModel):
    name:str = Field(...,description="用户名称",min_length=2)
    age:int = Field(...,description="用户年龄",gt=0,le=100)

@app.post("/testbody")
def testbody(
        user: str = Body(...,description="用户信息")    # 必须要加校验说明是请求体，不然默认会当作查询参数处理
):
    # 不可以声明str，因为接受了请求体参数，会把json串进行反序列化，反序列化成python的数据，框架会自动把json串编程字典类型
    # body是用来限定user整体必须是请求体参数
    # 默认请求体参数我们如果不用pydantic做校验，会反序列化为字典
    # user字典当中的键，怎么限定数据类型？——pydantic
    # 如果想限定user当中的键，就必须用pydantic来做校验，一旦使用pydantic类来校验注解类型，那么user就变成了pydantic对象不是字典

    print(user,type(user))
    return {"user": user} # 返回的时候返回的是字典;对象无所谓，都会默认序列化为json串，长相是一样的
# 字典和对象的本质是一样的，只是对象有所属类，字典没有所属类



# todo 四、接收混合参数
# 1、接收混合参数
class UserInfo(BaseModel):
    username:str = Field(...,description="用户名称",min_length=2)
    password:str = Field(...,description="用户密码",min_length=6)

@app.post("/testmix/{id}")
def testmix(
        id:int = Path(...,description="用户id",gt=0),
        name:str = Query(...,description="用户名称",min_length=2),
        age:int = Query(...,description="年龄",gt=0,le=100),
        user_info:UserInfo = Body(...,description="用户信息")
):
    return {"id": id, "name": name, "age": age, "user_info": user_info}


# 2、接收混合参数也可以把参数分为两大类：一大类是键值对参数；另一大类是请求体参数
# 路径参数和查询参数都属于键值对参数，此时可以使用普通类加fastapi给我们的依赖注入来实现接收，缺点就是验证不好做
# 请求体参数不变，还是使用pydantic做校验

class KeywordParams:
    def __init__(self,id,name,age):
        self.id = id
        self.name = name
        self.age = age
# 但是普通类，就只能自己写if判断做校验

# Depends是fastapi给我们的一个函数，它可以自动帮我们去做对象的实例化，并且自动帮我们去把对象的属性进行上下文解析初始化
# 它的参数必须是一个能执行调用的数据类型，要么就是类要么就是函数，
# 我们把我们的类当参数传递给Depends，它会帮我们自动实例化对象，切记给Depends的类或者函数不能自己调用,不能自己调用的意思是其他地方也不能调用吗？
# 还是说传入的时候不能Depends(KeywordParams)

@app.post("/testmax/{id}")
def testmax(
        keyword_params:KeywordParams=Depends(KeywordParams), # 依赖注入，把路径参数和查询参数封装成一个对象
        user_info:UserInfo = Body(...,description="用户信息")
):
    return {"id": keyword_params.id, "name": keyword_params.name, "age": keyword_params.age, "user_info": user_info}



# todo 五、接受请求头信息
@app.get("testheader")
def testheader(request: Request):
    print(request.headers)
    return {"header": request.headers.get("token")}


# todo 六、接收表单数据 文件 前端的上传文件功能
@app.post("/upload")
def upload_file(file: UploadFile = File(...,description="上传文件")):
    # 上传文件的业务：1、本地存储 2、转储到Minio中
    print(file.filename)
    print(file.content_type)
    print(file.size) # 字节大小
    print(file.headers) # Headers中的"name"值得是键的名字
    print(file.file) # 文件的内容
    img_dir = "./images"
    img_dir_obj = pathlib.Path(img_dir)
    if not img_dir_obj.exists():
        img_dir_obj.mkdir(parents=True,exist_ok=True)
    # images 需要实时监控,需要定时清理

    file_name = str(uuid.uuid4())[:9] + file.filename # uuid4生成的全是唯一随机数，取前8位作为文件名
    
    with open(img_dir_obj / file_name, "wb") as f:
        # f.write(file.file.read()) # 一口气读完放进内存, 容易内存爆炸, 不这样做
        shutil.copyfileobj(fsrc=file.file, # 从哪里读
                           fdst=f, # 写到哪里
                           length=1024*1024*10) # 一次性读多少,这里是10M
        # 转储
        return {
            "message":"ok",
            "file_name":file_name,
            "url":"url"
        } # minio 自己拼

#如果是想要打断点调试可以使用下面启动方式 本地服务器
if __name__ == '__main__':
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000
    )


