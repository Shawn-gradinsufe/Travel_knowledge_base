import shutil
import time
import requests
from pathlib import Path
from typing import Any

from atguigu.import_process.base import NodeBase
from atguigu.config.config import MineruConfig
from atguigu.import_process.state import ImportGraphState
from atguigu.tool.logger import logger


class NodePDFToMD(NodeBase):
    """
    PDF 转 Markdown 节点：PDF结构化解析
    """

    name = "node_pdf_to_md"

    def process(self, state: ImportGraphState):
        local_dir_obj, local_file_path, local_file_path_obj = self.check_pdf_path(state)

        # 上传文件至Mineru实现PDF到MD的转换
        batch_id = self.upload_pdf_file(local_file_path, local_file_path_obj)

        # 上传成功，Mineru返回batch_id，拿着batch_id轮询获取压缩包路径
        url = self.get_zip_url(batch_id)

        # 得到了解析好的文件路径，将文件下载到本地的zip文件当中
        md_content, new_md_file_path_obj = self.handler_md_file(local_dir_obj, local_file_path_obj, url)

        return {
            "md_path" : str(new_md_file_path_obj),
            "md_content" : md_content
        }

    def handler_md_file(self, local_dir_obj: Path, local_file_path_obj: Path, url) -> tuple[str, Path]:
        zip_res = requests.get(url)
        if zip_res.status_code != 200:
            logger.error("下载压缩包的内容请求失败")
            raise ValueError("下载压缩包的内容请求失败")
        # 下载成功后内容保存在内存中，此时未落盘

        zip_content = zip_res.content  # 获取压缩包的内容
        zip_file_path_obj = local_dir_obj / f"{local_file_path_obj.stem}.zip"
        with open(zip_file_path_obj, 'wb') as f:
            f.write(zip_content)
            # 真正落盘，将内存中下载的压缩包内容写入本地压缩文件中

        # 把下载的zip文件解压到本地
        import zipfile
        unzip_dir_obj = local_dir_obj / f"{local_file_path_obj.stem}"  # 创建解压缩的文件目录，将.zip压缩包内的文件放进来
        # 幂等性删除
        if unzip_dir_obj.exists():
            shutil.rmtree(unzip_dir_obj)  # 递归删除，有没有都删，目的是解决重复解压时，新旧解析结果混杂的问题
        unzip_dir_obj.mkdir(parents=True, exist_ok=True)

        # 打开zip压缩文件，把文件当中的内容解压到指定的目录当中
        with zipfile.ZipFile(zip_file_path_obj) as unzip_content_handler:
            unzip_content_handler.extractall(unzip_dir_obj)

        # 把解压出来的文件进行改名处理
        # 第一步找到老文件的位置
        old_md_file_path_obj = unzip_dir_obj / f"full.md"
        # 第二步改名处理，但是没有落盘，返回新的文件路径对象
        new_md_file_path_obj = old_md_file_path_obj.with_name(f"{local_file_path_obj.stem}.md")
        # 第三步真正的改名处理，落盘
        old_md_file_path_obj.rename(new_md_file_path_obj)

        with open(new_md_file_path_obj, 'r', encoding='utf-8') as f:
            md_content = f.read()
        return md_content, new_md_file_path_obj

    def get_zip_url(self, batch_id) -> Any:

        # 拿着上传得到的batch_id去轮询获取mineru转化的md的压缩包路径
        token = MineruConfig.mineru_token
        query_url = f"https://mineru.net/api/v4/extract-results/batch/{batch_id}"
        header = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}"
        }

        total_time = 120
        start_time = time.time()

        # 轮询获取 隔2秒发一次请求 直到拿到需要的结果
        while True:
            # 检查是否超时
            if time.time() - start_time > total_time:
                logger.error("获取mineru转化的md的压缩包路径请求超时")
                raise TimeoutError("获取mineru转化的md的压缩包路径请求超时")

            try:
                res = requests.get(query_url, headers=header, timeout=10)

                # 判断网络请求是否成功
                if res.status_code != 200:
                    logger.warning(f"请求状态码非200: {res.status_code}，正在重试...")
                    time.sleep(2)
                    continue

                result = res.json()
                if result.get("code") != 0:
                    logger.warning(f"接口返回错误码: {result.get('code')}，正在重试...")
                    time.sleep(2)
                    continue

                data = result.get("data")
                extract_results = data.get("extract_result") if data else None

                # 防止返回的列表为空
                if not extract_results:
                    time.sleep(2)
                    continue

                item = extract_results[0]
                state = item.get("state")

                # 核心修改：状态不是 done 时，不要抛异常，而是等待继续轮询
                if state == "done":
                    zip_url = item.get("full_zip_url")
                    if zip_url:
                        return zip_url
                    else:
                        logger.error("解析状态为done，但未获取到 full_zip_url")
                        raise ValueError("解析完成但未找到压缩包下载地址")

                elif state in ["failed", "error"]:
                    logger.error(f"MinerU 解析失败，当前状态: {state}")
                    raise ValueError(f"MinerU 文件解析失败，状态: {state}")
                else:
                    # 状态可能是 pending, running 等，属于正常排队中，继续等待
                    # print(f"当前解析状态: {state}，继续等待...")
                    pass

            except requests.RequestException as e:
                logger.warning(f"网络请求发生异常: {e}，正在重试...")
            except Exception as e:
                # 如果是主动抛出的 ValueError 直接往外抛
                if isinstance(e, ValueError):
                    raise e
                logger.warning(f"发生未知异常: {e}，正在重试...")

            time.sleep(2)

    def upload_pdf_file(self, local_file_path: str, local_file_path_obj: Path) -> Any:
        import requests

        token = MineruConfig.mineru_token
        url = "https://mineru.net/api/v4/file-urls/batch"
        header = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}"
        }
        data = {
            "files": [
                {"name": f"{local_file_path_obj.name}", "data_id": "abcd"}
            ],
            "model_version": "vlm"
        }
        file_path = [local_file_path]
        
        # 至此需要发送的请求报文已经好了，下面是需要对响应进行判断
        # 请求是否成功？
        response = requests.post(url, headers=header, json=data)
        if response.status_code != 200:
            logger.error(f"上传文件请求失败")
            raise ValueError(f"上传文件请求失败")

        # 请求成功了之后，看数据是否成功获取？
        result = response.json()
        if result["code"] != 0:
            logger.error(f"上传文件请求数据获取失败")
            raise ValueError(f"上传文件请求数据获取失败")

        batch_id = result["data"]["batch_id"]
        urls = result["data"]["file_urls"]
        # 一次POST API请求对应一个batch_id，即一次批量文件解析任务，一次任务可以提交多个pdf文件
        # urls保存的是PDF文件的上传地址列表，而不是Mineru解析完成后的ZIP压缩包下载地址
        for i in range(0, len(urls)):
            with open(file_path[i], 'rb') as f:
                res_upload = requests.put(urls[i], data=f)
                if res_upload.status_code == 200:
                    print(f"{urls[i]} 上传成功")
                else:
                    print(f"{urls[i]} 上传失败")
        return batch_id

    def check_pdf_path(self, state: ImportGraphState) -> tuple[Path, str, Path]:
        local_file_path = state.get("local_file_path")
        local_dir = state.get("local_dir")
        # 是否指定了文件目录？
        if not local_file_path:
            logger.error("local_file_path不能为空")
            raise ValueError("local_file_path不能为空")

        # 目录下的文件是否存在？
        local_file_path_obj = Path(local_file_path)
        if not local_file_path_obj.exists():
            logger.error("local_file_path文件不存在")
            raise ValueError("local_file_path文件不存在")

        # 输出的文件目录是否指定？
        if not local_dir:
            logger.error("local_dir不能为空")
            raise ValueError("local_dir不能为空")

        # 输出的文件目录是否存在?不存在就递归创建文件夹。
        local_dir_obj = Path(local_dir)
        if not local_dir_obj.exists():
            local_dir_obj.mkdir(parents=True, exist_ok=True)
        return local_dir_obj, local_file_path, local_file_path_obj


if __name__ == '__main__':
    node = NodePDFToMD()
    init_state = {
        "local_file_path" : r"E:\Python_projects\output\hak180产品安全手册.pdf",
        "local_dir" : r"E:\Python_projects\output"
    }

    result = node(init_state)
    logger.info(result)


