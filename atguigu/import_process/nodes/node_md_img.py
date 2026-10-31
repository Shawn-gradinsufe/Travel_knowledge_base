import base64
import os
import re
import time
from collections import deque
from pathlib import Path
from typing import Any

from langchain.chat_models import init_chat_model
from minio.deleteobjects import DeleteObject

from atguigu.import_process.base import NodeBase
from atguigu.config.config import LLMConfig, MinioConfig
from atguigu.import_process.state import ImportGraphState
from atguigu.tool.json_format import json_format
from atguigu.tool.logger import logger
from atguigu.tool.minio_client_tool import get_minio_client
from datetime import datetime

class NodeMDImg(NodeBase):
    """
    MarkDown图片处理节点：多模态图片理解
    """

    name = "node_md_img"

    def process(self, state: ImportGraphState):
        md_content, md_path_obj = self.get_md_content(state)

        # 读取了md文件的内容，需要找到图片的位置，通过正则匹配图片的名字找图片在文档中的位置
        # 获取本地图片的目录，如果不存在，就直接返回原来的内容，因为没有图片需要处理
        image_dir = md_path_obj.parent / "images"
        if not image_dir.exists():
            return {
                "md_content":md_content
            }

        # 把一个目录下当中所有的文件名字组成列表，包括目录名
        image_names = os.listdir(image_dir)
        # print(image_names)
        if not image_names:
            return {
                "md_content": md_content
            }

        image_with_context_list = self.get_image_with_context_list(image_dir, image_names, md_content)

        image_with_summary_list = self.get_image_with_summary_list(image_with_context_list)

        image_with_summary_url_list = self.get_image_with_summary_url_list(image_with_summary_list, md_path_obj)

        md_content, new_md_path_obj = self.replace_md_content(image_with_summary_url_list, md_content, md_path_obj)

        return {
            "md_content": md_content,
            "md_path": str(new_md_path_obj)
        }

    def replace_md_content(self, image_with_summary_url_list: list[Any], md_content: Path, md_path_obj: str) -> tuple[
        str | bytes | Any, Any]:
        # 把md_content中的图片替换成在线url链接
        for image_with_summary_url in image_with_summary_url_list:
            pattern = re.compile(r"!\[.*?\]\(.*?" + re.escape(image_with_summary_url.get("image_name")) + r"\)")
            md_content = pattern.sub(
                lambda _: f"![{image_with_summary_url.get('summary')}]({image_with_summary_url.get('url')})",
                md_content)

        # 构造最新的md文件路径，把替换完成的内容写到最新的文件
        new_md_path_obj = md_path_obj.parent / f"{md_path_obj.stem}_new.md"
        with open(new_md_path_obj, "w", encoding="utf-8") as f:
            f.write(md_content)
        return md_content, new_md_path_obj

    def get_image_with_summary_url_list(self, image_with_summary_list: list[Any], md_path_obj: str) -> list[Any]:
        # 得到了大模型返回的摘要,接下来继续得到url
        # 上传图片获取图片的在线url
        minio_client = get_minio_client()
        # 构造上传图片在桶里面的目录(除了桶和文件名字,中间的就是目录)
        upload_dir = f"{MinioConfig.minio_img_dir}/{datetime.now().strftime('%Y%m%d')}/{md_path_obj.stem}"
        # 本来我们准备好上传的目录之后就可以调用工具进行上传，但是上传之前我们都要去做一个幂等性删除，图片如果存在了就删除
        # 幂等性删除
        # 1、根据工具从minio当中获取老文件
        bucket_name = MinioConfig.minio_bucket_name
        old_image_generator = minio_client.list_objects(
            bucket_name=bucket_name,
            prefix=upload_dir,
            recursive=True,
        )
        # print("=========", old_image_generator)
        # 2、把老文件转化为delete_object_list
        delete_object_list = [DeleteObject(obj.object_name) for obj in old_image_generator]
        # 3、调用工具删除minio当中的老文件
        errors = minio_client.remove_objects(
            bucket_name=bucket_name,
            delete_object_list=delete_object_list
        )

        for error in errors:
            logger.warning("error occurred when deleting object", error)

        image_with_summary_url_list = []
        for image_with_summary in image_with_summary_list:
            minio_client.fput_object(
                bucket_name=MinioConfig.minio_bucket_name,
                object_name=f"{upload_dir}/{image_with_summary.get('image_name')}",
                file_path=image_with_summary.get("image_path"),
            )

            url = f"http://{MinioConfig.minio_endpoint}/{bucket_name}/{upload_dir}/{image_with_summary.get('image_name')}"
            image_with_summary_url_list.append({
                **image_with_summary,
                "url": url
            })
        return image_with_summary_url_list

    def get_image_with_summary_list(self, image_with_context_list: list[Any]) -> list[Any]:
        # 拿着图片的上下文、图片的内容、自己写的提示词、交给大模型去整理摘要(视觉大模型)
        llm = init_chat_model(
            model=LLMConfig.vl_model,
            model_provider='openai',
            api_key=LLMConfig.openai_api_key,
            base_url=LLMConfig.openai_api_base,
            temperature=LLMConfig.llm_default_temperature
        )

        dq = deque(maxlen=30)
        # 把摘要总结完成暂存到列表
        image_with_summary_list = []

        for image_with_context in image_with_context_list:
            current_time = time.time()
            # 滑动窗口实现限频
            while dq and current_time - dq[0] > 60:
                dq.popleft()

            if len(dq) >= dq.maxlen:
                need_wait_time = 60 - (current_time - dq[0])
                if need_wait_time > 0:
                    time.sleep(need_wait_time)
                current_time = time.time()

                while dq and current_time - dq[0] > 60:
                    dq.popleft()
            dq.append(current_time)

            # 构建提示词消息messages(4中message对象)
            # 整理图片的内容交给大模型有两种方式，一种是把图片的二进制数据发给大模型，一种是把图片的URL发给大模型
            with open(image_with_context.get("image_path"), "rb") as f:
                image_data = f.read()
                base64_data = base64.b64encode(image_data).decode("utf-8")

                messages = [{
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{base64_data}",
                            },
                        },
                        {"type": "text", "text": f"""
                            这是一张图片，图片上文部分为"{image_with_context.get("pre_text")}"，
                            下文部分为"{image_with_context.get("post_text")}"，请用中文简要总结这张图片的摘要,字数在50字以内。"""},
                    ],
                }, ]

                res = llm.invoke(input=messages)

                image_with_summary_list.append({
                    "image_name": image_with_context.get("image_name"),
                    "summary": res.content,
                    "image_path": image_with_context.get("image_path")
                })
        return image_with_summary_list

    def get_image_with_context_list(self, image_dir, image_names: list[str] | list[bytes],
                                    md_content: Path) -> list[Any]:
        IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ",webp"}

        image_with_context_list = []  # 找到每张图片的上下文后先暂存，后面要用到就从这个列表当中去拿

        for image_name in image_names:
            suffix = Path(image_name).suffix
            if suffix.lower() not in IMAGE_EXTENSIONS:
                logger.warning("图片的后缀名不正确")
                continue
            pattern = re.compile(r"!\[.*?\]\(.*?" + re.escape(image_name) + r"\)")
            # compile将正则表达式字符串提前编译成一个可复用的Pattern对象，
            # 之后这个对象可以调用search()、match()、findall()、sub()、split() 等方法做匹配

            match = pattern.search(md_content)  # 从内容当中查找正则相关的子串，找到第一个就结束，如果没有找到，就返回None
            if not match:
                logger.warning("没有找到图片的引用")
                continue

            start, end = match.span()  # 拿到每张图片在内容当中的起始位置和结束位置
            pre_text = md_content[max(0, start - 300):start]  # 假设图片上下文长度为300,可以根据实际情况调整长度
            post_text = md_content[end:min(len(md_content), end + 300)]
            image_with_context_list.append({
                "image_name": image_name,
                "pre_text": pre_text,
                "post_text": post_text,
                "image_path": str(image_dir / image_name)
            })
        return image_with_context_list

    def get_md_content(self, state: ImportGraphState) -> tuple[Path, str]:
        md_path = state.get("md_path")
        if not md_path:
            logger.error("未找到md文件路径")
            raise ValueError("未找到md文件路径")

        md_path_obj = Path(md_path)
        if not md_path_obj.exists():
            logger.error("未找到md文件")
            raise ValueError("未找到md文件")

        # 文件路径有了，读取md文件内容
        with open(md_path_obj, 'r', encoding='utf-8') as f:
            md_content = f.read()
        return md_content, md_path_obj


if __name__ == '__main__':
    node=NodeMDImg()
    init_state = {
        "md_path" : r"E:\Python_projects\output\hak180产品安全手册\hak180产品安全手册.md"
    }
    result = node(init_state)
    logger.info(json_format(result))