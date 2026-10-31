import json
import re
from typing import Any

from pymilvus import DataType

from atguigu.config.config import TourismConfig
from atguigu.config.prompt import ENTITY_EXTRACT_PROMPT, ENTITY_EXTRACT_SYSTEM_PROMPT
from atguigu.import_process.base import NodeBase
from atguigu.import_process.state import ImportGraphState
from atguigu.tool.get_bge_embeddings import get_bge_embedding
from atguigu.tool.get_llm_model import get_item_llm_model
from atguigu.tool.json_format import json_format
from atguigu.tool.logger import logger
from atguigu.tool.milvus_client_tool import get_milvus_client

# 明显不是实体的标题特征（分析性/结构性小标题）
NON_ENTITY_MARKERS = [
    "的", "吗", "么", "？", "?", "是不是", "要不要", "怎么", "为什么", "哪些", "多少",
    "优先级", "层", "游客", "人群", "建议", "结构", "概览", "差异", "逻辑", "安排",
    "决策点", "坑", "总结", "对比", "选择", "如何", "值得", "适合", "以上", "以下",
    "第一", "第二", "第三", "第 1", "第 2", "第 3", "第 4", "第 5", "第 6",
]


class NodeEntityExtract(NodeBase):
    """
    实体抽取节点：识别文档涉及的景点 / 酒店 / 餐厅 / 美食 / 片区，并回填到切片。

    为什么需要它：
    旅游语料是「攻略叙述体」，标题里既有实体名（亚龙湾、蜈支洲岛、海鲜），
    也有分析性小标题（第一层核心景点、东线和西线最好分天安排）。
    用户问「亚龙湾值得住吗」时，如果能把 query 对齐到实体名，检索精度会明显高于纯向量召回。

    策略：先用规则从标题里筛候选（零成本），再让大模型剔除误判并标注类型；
    大模型不可用时直接退回规则结果，保证导入流程不中断。
    """

    name = "node_entity_extract"

    def process(self, state: ImportGraphState):
        chunks = state.get("chunks")
        if not chunks:
            logger.error("没有获取到 chunks，无法抽取实体")
            raise ValueError("没有获取到 chunks，无法抽取实体")

        candidates = self.collect_candidates(chunks)
        entities = self.refine_with_llm(candidates, state)

        # 回填到每个切片
        self.backfill_chunks(chunks, entities)

        # 写入实体集合
        if entities:
            self.save_entities(entities, state)

        logger.info(
            f"实体抽取完成: {state.get('source_path')} -> {len(entities)} 个实体 "
            f"{[e['name'] for e in entities]}"
        )
        return {
            "chunks": chunks,
            "entity_names": entities,
        }

    # ------------------------------------------------------------------
    # 1. 规则候选
    # ------------------------------------------------------------------

    def collect_candidates(self, chunks: list[dict]) -> list[str]:
        seen: list[str] = []
        for chunk in chunks:
            title = (chunk.get("title") or "").strip()
            if not title or title in seen:
                continue
            if not (2 <= len(title) <= 14):
                continue
            if any(marker in title for marker in NON_ENTITY_MARKERS):
                continue
            # 纯数字/纯符号跳过
            if re.fullmatch(r"[\d\s.、%]+", title):
                continue
            seen.append(title)
        return seen

    # ------------------------------------------------------------------
    # 2. 大模型精修
    # ------------------------------------------------------------------

    def refine_with_llm(self, candidates: list[str], state: ImportGraphState) -> list[dict]:
        if not candidates:
            return []

        fallback = [{"name": c, "type": "其他"} for c in candidates]
        try:
            llm = get_item_llm_model()
            messages = [
                {"role": "system", "content": ENTITY_EXTRACT_SYSTEM_PROMPT},
                {"role": "user", "content": ENTITY_EXTRACT_PROMPT.format(
                    doc_title=state.get("doc_title") or "",
                    content_type=state.get("content_type") or "",
                    candidates="\n".join(f"- {c}" for c in candidates),
                )},
            ]
            res = llm.invoke(input=messages)
            data = self.parse_json(res.content)
            entities = [
                {"name": str(item.get("name", "")).strip(), "type": str(item.get("type", "其他")).strip()}
                for item in data.get("entities", [])
                if str(item.get("name", "")).strip()
            ]
            # 只保留确实出现在候选里的，防止模型编造
            valid = {c: True for c in candidates}
            entities = [e for e in entities if e["name"] in valid]
            if entities:
                return entities
            logger.warning("大模型未返回有效实体，退回规则结果")
            return fallback
        except Exception as e:
            logger.warning(f"实体抽取调用大模型失败，退回规则结果: {e}")
            return fallback

    @staticmethod
    def parse_json(text: str) -> dict[str, Any]:
        text = (text or "").strip()
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{[\s\S]*\}", text)
            if match:
                try:
                    return json.loads(match.group(0))
                except json.JSONDecodeError:
                    pass
        return {}

    # ------------------------------------------------------------------
    # 3. 回填
    # ------------------------------------------------------------------

    @staticmethod
    def backfill_chunks(chunks: list[dict], entities: list[dict]) -> None:
        name_to_type = {e["name"]: e["type"] for e in entities}
        for chunk in chunks:
            title = (chunk.get("title") or "").strip()
            if title in name_to_type:
                chunk["entity_name"] = title
                chunk["entity_type"] = name_to_type[title]
                continue
            # 标题不是实体时，从正文里找第一个出现的实体
            content = chunk.get("content") or ""
            hit = next((name for name in name_to_type if name in content), None)
            chunk["entity_name"] = hit or ""
            chunk["entity_type"] = name_to_type.get(hit, "") if hit else ""

    # ------------------------------------------------------------------
    # 4. 落库
    # ------------------------------------------------------------------

    def save_entities(self, entities: list[dict], state: ImportGraphState) -> None:
        client = get_milvus_client()
        collection = TourismConfig.entities_collection
        self.ensure_collection(client, collection)

        doc_id = state.get("doc_id")
        client.load_collection(collection)
        client.delete(collection_name=collection, filter=f'doc_id == "{doc_id}"')

        names = [e["name"] for e in entities]
        embeddings = get_bge_embedding(names)
        city_tags = ",".join(state.get("city_tags") or [])

        rows = []
        for idx, entity in enumerate(entities):
            rows.append({
                "entity_name": entity["name"],
                "entity_type": entity["type"][:20],
                "city_tags": city_tags,
                "content_type": state.get("content_type") or "",
                "doc_id": doc_id,
                "source_file": state.get("source_file") or "",
                "dense_vector": embeddings["dense"][idx],
                "sparse_vector": embeddings["sparse"][idx],
            })
        client.insert(collection_name=collection, data=rows)
        logger.info(f"实体写入 {collection}: {len(rows)} 条")

    @staticmethod
    def ensure_collection(client, collection: str) -> None:
        if client.has_collection(collection):
            return
        schema = client.create_schema(auto_id=True)
        (schema.add_field("id", DataType.INT64, is_primary=True)
               .add_field("entity_name", DataType.VARCHAR, max_length=100)
               .add_field("entity_type", DataType.VARCHAR, max_length=20)
               .add_field("city_tags", DataType.VARCHAR, max_length=200)
               .add_field("content_type", DataType.VARCHAR, max_length=20)
               .add_field("doc_id", DataType.VARCHAR, max_length=64)
               .add_field("source_file", DataType.VARCHAR, max_length=200)
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
        logger.info(f"已创建实体集合 {collection}")


if __name__ == '__main__':
    from pathlib import Path

    from atguigu.import_process.nodes.node_document_split import NodeDocumentSplit
    from atguigu.import_process.nodes.node_metadata_parse import NodeMetadataParse

    root = Path(TourismConfig.data_root)
    rel = "景点攻略/三亚景点推荐.md"
    target = root / rel
    base = {
        "md_path": str(target),
        "file_title": target.stem,
        "source_file": target.name,
        "source_path": rel,
    }
    meta = NodeMetadataParse()(base)
    split = NodeDocumentSplit()({**base, **meta})
    result = NodeEntityExtract()({**base, **meta, **split})
    logger.info(json_format(result["entity_names"]))
