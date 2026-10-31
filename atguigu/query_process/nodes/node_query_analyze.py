# atguigu/query_process/nodes/node_query_analyze.py

import json
import re
from typing import Any

from atguigu.config.config import TourismConfig
from atguigu.config.prompt import QUERY_ANALYZE_PROMPT, QUERY_ANALYZE_SYSTEM_PROMPT
from atguigu.config.tourism_dict import (
    display_city,
    has_fact_keyword,
    match_cities,
    match_content_types,
)
from atguigu.query_process.base import NodeBase
from atguigu.query_process.state import QueryGraphState
from atguigu.tool.filter_builder import build_city_expr
from atguigu.tool.get_bge_embeddings import get_bge_embedding
from atguigu.tool.get_llm_model import get_item_llm_model
from atguigu.tool.logger import logger
from atguigu.tool.milvus_client_tool import get_milvus_client, get_search_reqs, hybrid_search
from atguigu.tool.mongo_tool import get_recent_messages, save_chat_messages, update_message_meta

# 实体对齐阈值：大模型明确提出的实体，容忍度低一些；
# 用整句去匹配（没有大模型时的兜底路径），要求更高。
ENTITY_SCORE_LLM = 0.78
ENTITY_SCORE_QUERY = 0.82
# 最多保留几个实体。实体是"加严过滤"的条件，抽多了反而把正确答案滤掉
MAX_ENTITIES = 2


class NodeQueryAnalyze(NodeBase):
    """
    检索意图解析节点（替代原「商品名确认」节点）。

    产出三个检索维度：
      - cities：目的地城市标签（词典匹配优先，大模型兜底）
      - content_types：想看的内容类型（软过滤，可能为空）
      - entities：对齐后的实体名（先让大模型提，再用实体库做向量校验）

    与商品手册版本的行为差异（已与需求方确认）：
    识别不到城市时**不反问**，而是走跨城市推荐（`is_cross_city=True`），
    因为需求里的典型场景就是「带老人孩子适合去哪玩」这类没有目的地的问题。
    """

    name: str = "node_query_analyze"

    def process(self, state: QueryGraphState):
        original_query, session_id, message_id, history_list = self.get_history(state)
        history_str = "\n".join(
            f"{h.get('role')}: {h.get('text')}" for h in history_list
        )

        llm_result = self.analyze_with_llm(history_str, original_query)

        # 城市：词典优先（精确、零成本），大模型只在词典没命中时补位
        cities = match_cities(original_query) or self.normalize_llm_cities(llm_result.get("cities"))
        # 内容类型：同理
        content_types = match_content_types(original_query) or self.normalize_llm_types(
            llm_result.get("content_types")
        )
        is_fact = has_fact_keyword(original_query) or bool(llm_result.get("is_fact_query"))

        rewritten_query = (llm_result.get("rewritten_query") or "").strip() or original_query

        entities = self.align_entities(
            proposed=llm_result.get("entities") or [],
            query=rewritten_query,
            cities=cities,
        )

        is_cross_city = not cities

        # 只更新刚刚保存的这条用户消息，不再覆盖整个历史窗口
        update_message_meta(
            message_id=message_id,
            item_names=entities,
            rewritten_query=rewritten_query,
        )

        logger.info(
            f"意图解析: 城市={cities} 类型={content_types} 实体={entities} "
            f"跨城={is_cross_city} 事实型={is_fact} 改写={rewritten_query}"
        )

        return {
            "message_id": message_id,
            "original_query": original_query,
            "rewritten_query": rewritten_query,
            "cities": cities,
            "city_display": display_city(cities),
            "content_types": content_types,
            "entities": entities,
            "is_cross_city": is_cross_city,
            "is_fact_query": is_fact,
            "history": get_recent_messages(session_id),
        }

    # ------------------------------------------------------------------
    # 大模型解析
    # ------------------------------------------------------------------

    def analyze_with_llm(self, history_str: str, original_query: str) -> dict[str, Any]:
        try:
            llm = get_item_llm_model()
            messages = [
                {"role": "system", "content": QUERY_ANALYZE_SYSTEM_PROMPT},
                {"role": "user", "content": QUERY_ANALYZE_PROMPT.format(
                    history_text=history_str or "（无）",
                    original_query=original_query,
                )},
            ]
            res = llm.invoke(input=messages)
            return self.parse_json(res.content)
        except Exception as e:
            logger.warning(f"意图解析调用大模型失败，退回纯规则: {e}")
            return {}

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

    @staticmethod
    def normalize_llm_cities(raw: Any) -> list[str]:
        if not isinstance(raw, list):
            return []
        tags: list[str] = []
        for item in raw:
            for tag in match_cities(str(item)):
                if tag not in tags:
                    tags.append(tag)
        return tags

    @staticmethod
    def normalize_llm_types(raw: Any) -> list[str]:
        from atguigu.config.tourism_dict import normalize_content_type

        if not isinstance(raw, list):
            return []
        types: list[str] = []
        for item in raw:
            ctype = normalize_content_type(str(item))
            if ctype and ctype not in types:
                types.append(ctype)
        return types

    # ------------------------------------------------------------------
    # 实体对齐
    # ------------------------------------------------------------------

    def align_entities(self, proposed: list, query: str, cities: list[str]) -> list[str]:
        """
        把用户说法对齐到实体库里的标准名称，避免"蜈支洲"和"蜈支洲岛"各查各的。

        只保留置信度最高的前 MAX_ENTITIES 个：
        实体在检索里是**加严条件**，抽多了会把正确答案一起滤掉；
        实测把实体放开到 5 个时，模型还会把"菌子季型"这种非实体塞进提示词，干扰作答。
        """
        confirmed: list[str] = []

        for item in proposed:
            name = str(item).strip()
            if not name:
                continue
            hit = self.best_entity_match(name, cities, ENTITY_SCORE_LLM)
            if hit and hit not in confirmed:
                confirmed.append(hit)
            if len(confirmed) >= MAX_ENTITIES:
                break

        if not confirmed and query:
            hit = self.best_entity_match(query, cities, ENTITY_SCORE_QUERY)
            if hit:
                confirmed.append(hit)

        return confirmed[:MAX_ENTITIES]

    def best_entity_match(self, text: str, cities: list[str], threshold: float) -> str | None:
        try:
            client = get_milvus_client()
            collection = TourismConfig.entities_collection
            if not client.has_collection(collection):
                return None

            embeddings = get_bge_embedding([text])
            expr = build_city_expr(cities) or None
            reqs = get_search_reqs(
                dense_data=[embeddings["dense"][0]],
                sparse_data=[embeddings["sparse"][0]],
                dense_anns_field="dense_vector",
                sparse_anns_field="sparse_vector",
                limit=3,
                expr=expr,
            )
            res = hybrid_search(
                collection_name=collection,
                reqs=reqs,
                limit=3,
                output_fields=["entity_name", "entity_type", "city_tags"],
                ranker=(0.7, 0.3),
            )
            if not res or not res[0]:
                return None

            top = res[0][0]
            score = float(top.get("distance") or 0)
            name = (top.get("entity") or {}).get("entity_name")
            if score >= threshold:
                logger.info(f"实体对齐: 「{text}」-> {name} (score={score:.3f})")
                return name
            logger.info(f"实体对齐未达阈值: 「{text}」最相近={name} (score={score:.3f} < {threshold})")
            return None
        except Exception as e:
            logger.warning(f"实体对齐失败: {e}")
            return None

    # ------------------------------------------------------------------
    # 历史
    # ------------------------------------------------------------------

    def get_history(self, state: QueryGraphState):
        original_query = state.get("original_query")
        session_id = state.get("session_id")
        if not original_query:
            logger.error("原始问题不能为空")
            raise ValueError("原始问题不能为空")
        if not session_id:
            logger.error("会话ID不能为空")
            raise ValueError("会话ID不能为空")

        # 先取历史（不含本条），再把本条存进去
        history_list = get_recent_messages(session_id)
        message_id = save_chat_messages(session_id=session_id, role="user", text=original_query)
        return original_query, session_id, message_id, history_list


if __name__ == '__main__':
    from atguigu.tool.task_utils import create_queue

    create_queue("test_task")
    node = NodeQueryAnalyze()
    cases = [
        "三亚天涯海角门票多少钱",
        "带老人孩子适合去哪玩",
        "大理怎么玩三天",
        "亚龙湾值得住吗",
        "鼓浪屿怎么去",
    ]
    for q in cases:
        result = node({"task_id": "test_task", "session_id": "tour_test", "original_query": q})
        logger.info(f"{q} -> 城市={result['cities']} 类型={result['content_types']} "
                    f"实体={result['entities']} 跨城={result['is_cross_city']} 事实={result['is_fact_query']}")
