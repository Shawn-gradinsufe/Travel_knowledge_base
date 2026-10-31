# atguigu/query_process/nodes/node_search_embedding.py
from atguigu.config.config import TourismConfig
from atguigu.query_process.base import NodeBase
from atguigu.query_process.state import QueryGraphState
from atguigu.tool.filter_builder import search_with_soft_filter, to_chunk
from atguigu.tool.get_bge_embeddings import get_bge_embedding
from atguigu.tool.logger import logger


class NodeSearchEmbedding(NodeBase):
    """
    普通混合检索节点：用改写后的问题做 dense + sparse 双路检索。

    与商品手册版本的差异：过滤条件从 `item_name in [...]` 换成
    「城市 + 内容类型 + 实体」的软过滤组合（过滤太严会自动放宽）。
    """

    name: str = "node_search_embedding"

    def process(self, state: QueryGraphState):
        rewritten_query = state.get("rewritten_query")
        if not rewritten_query:
            logger.error("改写后的用户问题不能为空")
            raise ValueError("改写后的用户问题不能为空")

        embeddings = get_bge_embedding([rewritten_query])
        hits, level = search_with_soft_filter(
            collection=TourismConfig.chunks_collection,
            dense_data=[embeddings["dense"][0]],
            sparse_data=[embeddings["sparse"][0]],
            city_tags=state.get("cities"),
            content_types=state.get("content_types"),
            entities=state.get("entities"),
            ranker=(0.6, 0.4),
        )

        chunks = [to_chunk(hit) for hit in hits]
        logger.info(f"普通检索: 命中 {len(chunks)} 条，过滤级别={level}")
        return {
            "embedding_chunks": chunks,
            "filter_used": level,
        }


if __name__ == "__main__":
    node = NodeSearchEmbedding()
    result = node({
        "rewritten_query": "三亚亚龙湾的景点介绍",
        "cities": ["三亚"],
        "content_types": ["景点介绍"],
        "entities": ["亚龙湾"],
    })
    for c in result["embedding_chunks"][:5]:
        logger.info(f"[{c.get('city_display')}|{c.get('content_type')}|{c.get('breadcrumb')}] "
                    f"score={c.get('score'):.3f} {c.get('content')[:40]}")
