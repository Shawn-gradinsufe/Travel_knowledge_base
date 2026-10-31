# atguigu/query_process/nodes/node_search_embedding_hyde.py
from atguigu.config.config import TourismConfig
from atguigu.config.prompt import HYDE_PROMPT
from atguigu.query_process.base import NodeBase
from atguigu.query_process.state import QueryGraphState
from atguigu.tool.filter_builder import search_with_soft_filter, to_chunk
from atguigu.tool.get_bge_embeddings import get_bge_embedding
from atguigu.tool.get_llm_model import get_item_llm_model
from atguigu.tool.logger import logger


class NodeSearchEmbeddingHyde(NodeBase):
    """
    HyDE 检索节点：先让大模型写一段"假设性答案"，再用它去检索。

    与商品手册版本的差异：过滤条件换成城市/类型/实体组合；
    大模型不可用时返回空列表（不中断整条链路，RRF 会跳过这一路）。
    """

    name: str = "node_search_embedding_hyde"

    def process(self, state: QueryGraphState):
        rewritten_query = state.get("rewritten_query")
        if not rewritten_query:
            logger.error("改写后的用户问题不能为空")
            raise ValueError("改写后的用户问题不能为空")

        hyde_answer = self.generate_hypothetical_answer(rewritten_query)
        if not hyde_answer:
            logger.warning("HyDE 未生成假设性答案，跳过该路召回")
            return {"hyde_embedding_chunks": []}

        # 问题 + 假设答案一起编码，兼顾"问法"和"答法"
        embeddings = get_bge_embedding([rewritten_query, hyde_answer])
        hits, level = search_with_soft_filter(
            collection=TourismConfig.chunks_collection,
            dense_data=[embeddings["dense"][1]],
            sparse_data=[embeddings["sparse"][1]],
            city_tags=state.get("cities"),
            content_types=state.get("content_types"),
            entities=state.get("entities"),
            ranker=(0.7, 0.3),
        )

        chunks = [to_chunk(hit) for hit in hits]
        logger.info(f"HyDE 检索: 命中 {len(chunks)} 条，过滤级别={level}")
        return {"hyde_embedding_chunks": chunks}

    @staticmethod
    def generate_hypothetical_answer(rewritten_query: str) -> str:
        try:
            llm = get_item_llm_model()
            res = llm.invoke(input=[
                {"role": "user", "content": HYDE_PROMPT.format(rewritten_query=rewritten_query)}
            ])
            return (res.content or "").strip()
        except Exception as e:
            logger.warning(f"HyDE 生成失败: {e}")
            return ""


if __name__ == "__main__":
    node = NodeSearchEmbeddingHyde()
    result = node({
        "rewritten_query": "三亚亚龙湾适合什么样的游客",
        "cities": ["三亚"],
        "content_types": ["景点介绍"],
        "entities": ["亚龙湾"],
    })
    for c in result["hyde_embedding_chunks"][:5]:
        logger.info(f"[{c.get('breadcrumb')}] score={c.get('score'):.3f} {c.get('content')[:40]}")
