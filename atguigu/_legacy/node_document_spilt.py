import json
import re
from pathlib import Path
from typing import Any

from langchain_text_splitters import RecursiveCharacterTextSplitter

from atguigu.import_process.base import NodeBase
from atguigu.import_process.state import ImportGraphState
from atguigu.tool.json_format import json_format
from atguigu.tool.logger import logger


class NodeDocumentSplit(NodeBase):
    """
    文档切分节点：智能文档切片
    """

    name = "node_document_split"

    def process(self, state: ImportGraphState):
        # 第一步：获取完整的md文档内容和文件标题，为切分过程准备可靠的输入数据
        file_title, md_content = self.get_md_content(state)

        # 第二步：粗切，根据标题划分Section
        split_section_list = self.get_split_section_list(file_title, md_content)

        # 第三步：细切，长切短合，切分器内部实现
        final_chunk_list = self.get_final_chunk_list(file_title, split_section_list)

        # 把切分好的chunks变为json 存储到json文件，目的是为了下个节点要用的时候直接从json文档中去读
        # with open(r"E:\Python_projects\output\hak180产品安全手册\chunks.json","w",encoding="utf-8") as f:
        #     f.write(json_format(final_chunk_list))

        return {
            "chunks":final_chunk_list
        }

    def get_final_chunk_list(self, file_title: str, split_section_list: list[Any]):
        splitter = RecursiveCharacterTextSplitter(
            separators=["\n\n", "\n", "。", "！", "？", "；", "!", "?", ";", " "],
            chunk_size=300,
            chunk_overlap=50
        )
        final_chunk_list = []
        for split_section in split_section_list:
            # 获取每个区块的内容，判断内容的长度是不是超过指定的长度，超过就切分
            title = split_section.get("title")
            content = split_section.get("content")
            real_content = content[len(title) + 2:] if content.startswith("#") else content

            if len(real_content) < 300:
                final_chunk_list.append({
                    **split_section,  # **split_section的结果是字典解包，把外层{}去掉后，键值对返回
                    "part": 0  # 没有被切分的section编号为0，方便溯源
                })
                continue

            if "<table" in real_content:
                final_chunk_list.append({
                    **split_section,
                    "part": 0
                })
                continue

            for idx, split_text in enumerate(splitter.split_text(real_content)):
                # 把切成的每个小块文本,组装成一个chunk字典，存入final_chunk_list
                final_chunk_list.append({
                    "title": title,
                    "content": title + "\n\n" + split_text,
                    "file_title": file_title,
                    "part": idx
                })

        return final_chunk_list

    def get_split_section_list(self, file_title: str, md_content: str) -> list[Any]:
        # 判断#是否在代码围栏中
        # 不是代码围栏且以#开头就是标题
        split_line_list = md_content.split("\n")
        is_block = False  # 默认状态设为不在代码围栏中
        # code_pattern = r"^({`3,}|{~3,})" # 代码围栏的开头匹配
        code_pattern = r"^(`{3,}|~{3,})"
        title_pattern = r"^\s*#{1,6}\s+.+"

        marker = None
        start_index = 0
        temp_section_list = []
        for idx, split_line in enumerate(split_line_list):
            split_line = split_line.strip()
            # 判断这行是不是标题
            # 1、判断这行在不在代码围栏中
            match = re.match(code_pattern, split_line)
            if match:
                # 说明匹配到了```或~~~，然后判断是不是代码围栏的开始
                if not is_block:
                    # 如果说前后状态不一致，说明有碰到了代码围栏的边界，代码围栏边界判断的状态机要发生变化
                    # 初始状态为False，代表第一次not is_block是首次进入代码围栏，is_block需要更改为True，表示进入代码围栏
                    # 直至下一次再次匹配到```或~~~，not is_block就是False，此时直接跳转至else执行else以下的代码
                    is_block = True
                    marker = match.group(1)
                else:
                    if marker == match.group(1):
                        is_block = False
                        marker = None

            if not is_block and re.match(title_pattern, split_line):
                # 一定是标题，既不是代码围栏，又匹配到了title的开头
                temp_section_list.append(split_line_list[start_index:idx])
                start_index = idx

        temp_section_list.append(split_line_list[start_index:])
        # print(temp_section_list)
        # 把切分出来的每个小列表对应整理成字典，就是我们粗切出来的每个section
        split_section_list = []
        for temp_section in temp_section_list:
            content = "\n".join(temp_section).strip()
            title = temp_section[0] if content.startswith("#") else "无标题"
            split_section_list.append({
                "title": title,
                "content": content,
                "file_title": file_title
            })
        # print(split_section_list)

        # 得到了粗切的后的Section列表，里面包含title,content,file_title,保存file_title目的是因为万一不同的文档中有相同标题的情况
        return split_section_list

    def get_md_content(self, state: ImportGraphState) -> tuple[str, str]:
        md_path = state.get("md_path")
        if not md_path:
            logger.error("未提供md文件路径")
            raise ValueError("未提供文件路径")

        md_path_obj = Path(md_path)
        if not md_path_obj.exists():
            logger.error("文件不存在")
            raise FileNotFoundError("文件不存在")

        file_title = state.get("file_title")
        if not file_title:
            logger.error("文件名不存在")
            raise ValueError("文件名不存在")

        with open(md_path_obj, "r", encoding="utf-8") as f:
            md_content = f.read()

        md_content = md_content.replace("\r\n", "\n").replace("\r", "\n")
        return file_title, md_content


if __name__ == '__main__':
    node = NodeDocumentSplit()
    init_state = {
        "md_path":r"E:\Python_projects\output\hak180产品安全手册\hak180产品安全手册_new.md",
        "file_title":"hak180产品安全手册"
    }

    result = node(init_state)
    logger.info(json_format(result))





