from pymilvus import DataType

from atguigu.config.config import TourismConfig
from atguigu.import_process.base import NodeBase
from atguigu.import_process.state import ImportGraphState
from atguigu.tool.logger import logger
from atguigu.tool.milvus_client_tool import get_milvus_client

# 入库时保留的字段（chunk 里可能还带着中间态字段，不能直接塞给 Milvus）
STORED_FIELDS = [
    "doc_id", "doc_title", "title", "breadcrumb", "content", "part", "heading_level",
    "content_type", "city", "city_tags", "city_display",
    "entity_name", "entity_type", "topic", "source_file", "source_path",
    "dense_vector", "sparse_vector",
]


class NodeImportMilvus(NodeBase):
    """
    导入向量库节点。

    与商品手册版本的差异：
    1. schema 从「item_name + file_title」扩展为完整的旅游元数据维度；
    2. 幂等键从 file_title 换成 doc_id（由 source_path 派生），
       同名文件放在不同目录也不会互相覆盖；
    3. 城市用两个字段存：`city`（主城市，精确匹配）+ `city_tags`（逗号拼接，模糊匹配），
       避免依赖 ARRAY 类型带来的版本兼容问题。
    """

    name = "node_import_milvus"

    def process(self, state: ImportGraphState):
        chunks = state.get("chunks")
        if not chunks:
            logger.error("没有获取到 chunks，无法入库")
            raise ValueError("没有获取到 chunks，无法入库")

        doc_id = state.get("doc_id") or chunks[0].get("doc_id")
        if not doc_id:
            logger.error("缺少 doc_id，无法做幂等覆盖")
            raise ValueError("缺少 doc_id，无法做幂等覆盖")

        client = get_milvus_client()
        self.ensure_collection(client)

        # 幂等：先删掉该文档的旧切片，再整体写入
        client.load_collection(TourismConfig.chunks_collection)
        client.delete(
            collection_name=TourismConfig.chunks_collection,
            filter=f'doc_id == "{doc_id}"',
        )

        rows = [self.to_row(chunk) for chunk in chunks]
        res = client.insert(collection_name=TourismConfig.chunks_collection, data=rows)

        for idx, chunk in enumerate(chunks):
            chunk["id"] = res["ids"][idx]

        logger.info(
            f"入库完成: {state.get('source_path')} -> {len(rows)} 条切片，doc_id={doc_id}"
        )
        return {"chunks": chunks}

    @staticmethod
    def to_row(chunk: dict) -> dict:
        city_tags = chunk.get("city_tags") or []
        row = {key: chunk.get(key) for key in STORED_FIELDS if key in chunk}

        row["city"] = city_tags[0] if city_tags else ""
        row["city_tags"] = ",".join(city_tags)
        row["city_display"] = chunk.get("city_display") or ""
        row["entity_name"] = chunk.get("entity_name") or ""
        row["entity_type"] = chunk.get("entity_type") or ""
        row["breadcrumb"] = chunk.get("breadcrumb") or ""
        row["doc_title"] = chunk.get("doc_title") or ""
        row["topic"] = chunk.get("topic") or ""
        row["heading_level"] = int(chunk.get("level") or 0)
        row["part"] = int(chunk.get("part") or 0)
        return row

    @staticmethod
    def ensure_collection(client) -> None:
        collection = TourismConfig.chunks_collection
        if client.has_collection(collection):
            return

        schema = client.create_schema(auto_id=True)
        (schema.add_field("id", DataType.INT64, is_primary=True)
               .add_field("doc_id", DataType.VARCHAR, max_length=64)
               .add_field("doc_title", DataType.VARCHAR, max_length=200)
               .add_field("title", DataType.VARCHAR, max_length=200)
               .add_field("breadcrumb", DataType.VARCHAR, max_length=400)
               .add_field("content", DataType.VARCHAR, max_length=10000)
               .add_field("part", DataType.INT64)
               .add_field("heading_level", DataType.INT64)
               .add_field("content_type", DataType.VARCHAR, max_length=20)
               .add_field("city", DataType.VARCHAR, max_length=50)
               .add_field("city_tags", DataType.VARCHAR, max_length=200)
               .add_field("city_display", DataType.VARCHAR, max_length=200)
               .add_field("entity_name", DataType.VARCHAR, max_length=100)
               .add_field("entity_type", DataType.VARCHAR, max_length=20)
               .add_field("topic", DataType.VARCHAR, max_length=300)
               .add_field("source_file", DataType.VARCHAR, max_length=200)
               .add_field("source_path", DataType.VARCHAR, max_length=500)
               .add_field("dense_vector", DataType.FLOAT_VECTOR, dim=1024)
               .add_field("sparse_vector", DataType.SPARSE_FLOAT_VECTOR))

        index_params = client.prepare_index_params()
        index_params.add_index(
            field_name="dense_vector", index_name="dense_idx",
            index_type="IVF_FLAT", metric_type="COSINE", params={"nlist": 128, "nprobe": 10},
        )
        index_params.add_index(
            field_name="sparse_vector", index_name="sparse_idx",
            index_type="SPARSE_INVERTED_INDEX", metric_type="IP",
        )
        client.create_collection(collection_name=collection, schema=schema, index_params=index_params)
        logger.info(f"已创建切片集合 {collection}")
