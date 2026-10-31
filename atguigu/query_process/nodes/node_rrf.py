# atguigu/query_process/nodes/node_rrf.py

from atguigu.config.config import TourismConfig
from atguigu.query_process.base import NodeBase
from atguigu.query_process.state import QueryGraphState
from atguigu.tool.logger import logger

# RRF 的平滑常数，取经验值 60
RRF_K = 60
# 每路召回的权重
RRF_WEIGHTS = {"embedding": 1.0, "hyde": 1.0}


class NodeRrf(NodeBase):
    """
    RRF 融合节点。

    在原实现基础上加了「小库直通」：
    旅游语料只有 30 篇文档、几百个切片，过滤后候选往往不到 20 条，
    这种情况下多路加权融合的收益很小，反而可能把本来排第一的精确命中稀释掉。
    所以候选少时直接按各路原始分数合并去重，跳过 RRF 加权。

    这个开关不是省事，是刻意的降级设计：
    重武器要用在候选多、噪声大的场景，小库上硬套只会变差。
    """

    name: str = "node_rrf"

    def process(self, state: QueryGraphState):
        embedding_chunks = state.get("embedding_chunks") or []
        hyde_chunks = state.get("hyde_embedding_chunks") or []

        total = len(embedding_chunks) + len(hyde_chunks)
        if total == 0:
            logger.warning("两路召回都没有结果")
            return {"rrf_chunks": [], "small_kb": True}

        if total < TourismConfig.small_kb_threshold:
            merged = self.merge_direct(embedding_chunks, hyde_chunks)
            logger.info(f"小库直通：候选 {total} 条 < 阈值 {TourismConfig.small_kb_threshold}，跳过 RRF 加权")
            return {"rrf_chunks": merged, "small_kb": True}

        rrf_chunks = self.fuse(embedding_chunks, hyde_chunks)
        logger.info(f"RRF 融合：{total} 条候选 -> {len(rrf_chunks)} 条")
        return {"rrf_chunks": rrf_chunks, "small_kb": False}

    @staticmethod
    def merge_direct(embedding_chunks: list, hyde_chunks: list) -> list:
        """直通模式：按 embedding -> hyde 的顺序合并，按 id 去重，保留原始分数排序。"""
        seen = set()
        merged = []
        for chunk in list(embedding_chunks) + list(hyde_chunks):
            key = chunk.get("id")
            if key in seen:
                continue
            seen.add(key)
            merged.append(chunk)
        merged.sort(key=lambda x: x.get("score") or 0, reverse=True)
        return merged

    @staticmethod
    def fuse(embedding_chunks: list, hyde_chunks: list) -> list:
        rrf_dict: dict = {}

        for source, chunks in (("embedding", embedding_chunks), ("hyde", hyde_chunks)):
            weight = RRF_WEIGHTS[source]
            for idx, chunk in enumerate(chunks):
                score = weight / (RRF_K + idx + 1)
                key = chunk.get("id")
                if key in rrf_dict:
                    rrf_dict[key]["score"] += score
                    rrf_dict[key]["rrf_sources"].append(source)
                else:
                    item = dict(chunk)
                    item["score"] = score
                    item["rrf_sources"] = [source]
                    rrf_dict[key] = item

        return sorted(rrf_dict.values(), key=lambda x: x["score"], reverse=True)[:10]
