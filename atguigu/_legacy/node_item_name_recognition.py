import json
from typing import Any

from pymilvus import DataType, MilvusClient

from atguigu.import_process.base import NodeBase
from atguigu.config.config import MilvusConfig
from atguigu.config.prompt import ITEM_NAME_SYSTEM_PROMPT, ITEM_NAME_USER_PROMPT_TEMPLATE
from atguigu.import_process.state import ImportGraphState
from atguigu.tool.get_bge_embeddings import get_bge_embedding
from atguigu.tool.get_llm_model import get_item_llm_model
from atguigu.tool.logger import logger
from atguigu.tool.milvus_client_tool import get_milvus_client


class NodeItemNameRecognition(NodeBase):
    """
    主体识别节点：主体识别与标签提取
    """

    name = "node_item_name_recognition"

    def process(self, state: ImportGraphState):
        # 0、获取数据
        chunks, file_title = self.get_chunks(state)

        # 1、拿到部分的chunk 把这些chunk的内容拼接起来变成一个字符串
        chunks_str = self.get_chunks_str(chunks, file_title)

        # 2、调用大模型把拼接的字符串作为prompt，整理总结主体（商品名）
        item_name = self.get_item_name(chunks_str, file_title)

        # 3、启用milvus数据库，创建milvus连接，并创建表collection
        milvus_client = self.create_milvus_collection()

        # 4、先幂等性删除，把整理的商品名需要向量化存储到milvus，把识别的商品名回填到每个chunk，备份

        self.insert_data(chunks, file_title, item_name, milvus_client)

        return {
            "chunks":chunks,
            "item_name": item_name
        }

    def insert_data(self, chunks: list, file_title: str, item_name, milvus_client: MilvusClient):
        # 4.1 幂等性删除
        # 加载到表中
        milvus_client.load_collection(MilvusConfig.item_name_collection)
        # 为了让过滤条件字符串不出现语法错误，需要把一些特殊字符进行替换
        safe_title = file_title.replace("\\", "\\\\").replace("\'", "\\'").replace('\"', '\\"')
        filter = f"file_title== '{safe_title}'"
        # 这里需要用单引号'包裹{file_title}，因为如果不包裹的结果，Milvus无法将没有引号包裹的Hak180烫金机识别为字符串字面量，导致表达式解析错误
        milvus_client.delete(
            collection_name=MilvusConfig.item_name_collection,
            filter=filter
        )

        # 4.2 把item_name向量化添加到milvus
        embeddings = get_bge_embedding([item_name])

        data = {
            "item_name": item_name,
            "file_title": file_title,
            "dense_vector": embeddings.get("dense")[0],
            "sparse_vector": embeddings.get("sparse")[0],
        }

        res = milvus_client.insert(
            collection_name=MilvusConfig.item_name_collection,
            data=data
        )

        for chunk in chunks:
            chunk["item_name"] = item_name

        # with open(r"E:\Python_projects\output\hak180产品安全手册\chunks_item_name.json", "w", encoding="utf-8") as f:
        #     f.write(json_format(chunks))

    def create_milvus_collection(self) -> MilvusClient:
        milvus_client = get_milvus_client()
        # 判断有没有当前要准备创建的表
        if not milvus_client.has_collection(collection_name=MilvusConfig.item_name_collection):
            # 创建表：1、创建结构schema 2、创建索引index 3、创建表

            # 3.1、创建结构schema
            schema = milvus_client.create_schema(
                auto_id=True
            )

            (schema.add_field(
                field_name="id",
                datatype=DataType.INT64,
                is_primary=True,
            ).add_field(
                field_name="item_name",
                datatype=DataType.VARCHAR,
                max_length=100
            ).add_field(
                field_name="file_title",
                datatype=DataType.VARCHAR,
                max_length=100
            ).add_field(
                field_name="dense_vector",
                datatype=DataType.FLOAT_VECTOR,
                dim=1024
            ).add_field(
                field_name="sparse_vector",
                datatype=DataType.SPARSE_FLOAT_VECTOR,
            ))

            # 创建索引
            index_params = milvus_client.prepare_index_params()
            # 稠密向量的索引
            index_params.add_index(
                field_name="dense_vector",
                index_name="dense_vector_index",
                index_type="IVF_FLAT",
                metric_type="COSINE",
                params={"nlist": 128, "nprobe": 10}
            )
            # 稀疏向量的索引
            index_params.add_index(
                field_name="sparse_vector",
                index_name="sparse_vector_index",
                index_type="SPARSE_INVERTED_INDEX",
                metric_type="IP",
            )

            # 创建表
            milvus_client.create_collection(
                collection_name=MilvusConfig.item_name_collection,
                schema=schema,
                index_params=index_params
            )
        return milvus_client

    def get_item_name(self, chunks_str: str, file_title: str) -> Any:
        llm = get_item_llm_model()

        messages = [
            {"role": "system", "content": ITEM_NAME_SYSTEM_PROMPT},
            {"role": "user",
             "content": ITEM_NAME_USER_PROMPT_TEMPLATE.format(file_title=file_title, context=chunks_str)},
        ]

        res = llm.invoke(input=messages)
        # print(res)
        # print(res.content)
        # Brother HAK 180 烫金机
        # 大模型返回的结果可能有空格，去除
        item_name = res.content.replace("\n", "").replace("\t", "").replace(" ", "")
        if not item_name:
            item_name = file_title
        return item_name

    def get_chunks_str(self, chunks: list, file_title: str) -> str:
        chunk_k_list = chunks[:15]
        max_length = 10000
        chunks_str = ""
        for idx, chunk in enumerate(chunk_k_list, start=1):
            title = chunk.get("title")
            content = chunk.get("content")
            chunk_text = f"[切片{idx}\n文件名:{file_title}\n标题:{title}\n内容:{content}\n\n]"
            chunks_str += chunk_text
            if len(chunks_str) > max_length:
                break
        chunks_str = chunks_str[:max_length]
        return chunks_str

    def get_chunks(self, state: ImportGraphState) -> tuple[list, str]:
        chunks = state.get("chunks")
        file_title = state.get("file_title")

        if not chunks:
            logger.error("chunks不能为空")
            raise ValueError("chunks不能为空")

        if not file_title:
            logger.error("文件名不能为空")
            raise ValueError("文件名不能为空")
        return chunks, file_title


if __name__ == '__main__':
    node = NodeItemNameRecognition()
    with open(r"E:\Python_projects\output\hak180产品安全手册\chunks.json","r",encoding="utf-8") as f:
        chunks = json.load(f)

    init_state = {
        "chunks": chunks,
        "file_title": "hak180产品安全手册"
    }

    result = node(init_state)
    logger.info(result)