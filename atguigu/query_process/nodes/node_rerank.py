# atguigu/query_process/nodes/node_rerank.py

from atguigu.config.config import TourismConfig
from atguigu.query_process.base import NodeBase
from atguigu.query_process.state import QueryGraphState
from atguigu.tool.logger import logger
from atguigu.tool.rerank_tool import text_rerank

# 动态 TopK 参数（沿用原实现的断崖检测思路）
RERANK_MAX_TOPK = 10
RERANK_MIN_TOPK = 3
RERANK_GAP_RATIO = 0.25
RERANK_GAP_ABS = 0.20


class NodeRerank(NodeBase):
    """
    重排序节点：Cross-Encoder 精确打分 + 断崖检测动态截断。

    新增的两点：
    1. **本地优先**：联网结果的分数乘一个惩罚系数（默认 0.85），
       保证同样相关的情况下本地知识库排在前面；
       但如果用户问的是价格/开放时间这类事实字段，则不打折——
       这类信息本地本来就没有，让联网结果正常竞争才对。
    2. **重排失败降级**：rerank 接口不可用时退回 RRF 分数排序，不中断问答。
    """

    name: str = "node_rerank"

    def process(self, state: QueryGraphState):
        rewritten_query = state.get("rewritten_query") or state.get("original_query") or ""
        rrf_chunks = state.get("rrf_chunks") or []
        web_docs = state.get("web_search_docs") or []
        is_fact_query = bool(state.get("is_fact_query"))

        merged = self.normalize(rrf_chunks, web_docs)
        if not merged:
            logger.warning("没有可重排的候选")
            return {"reranked_docs": []}

        ranked = self.rerank(rewritten_query, merged)
        ranked = self.apply_web_penalty(ranked, is_fact_query)
        ranked, web_kept = self.gate_web(ranked, rrf_chunks, is_fact_query)

        final = self.cut_by_cliff(ranked)
        logger.info(
            f"重排完成：候选 {len(merged)} 条 -> 保留 {len(final)} 条"
            f"（事实型问题={is_fact_query}，保留联网结果={web_kept}）"
        )
        return {"reranked_docs": final}

    @staticmethod
    def gate_web(ranked: list[dict], rrf_chunks: list, is_fact_query: bool) -> tuple[list[dict], bool]:
        """
        联网结果的准入判断（"本地优先"的落地实现）。

        只把联网结果当**补位**，不当竞争者：
          - 用户在问价格/开放时间这类事实 → 放行（本地本来就没有）
          - 本地召回不足 3 条，或本地最高分低于 0.55 → 放行（本地覆盖不住）
          - 其余情况直接丢弃联网结果

        为什么必须这么做：实测发现，如果不加这道闸，"大理怎么玩三天"这种
        本地完全能答的问题也会混进一堆 SEO 页，模型会把联网里的价格和本地内容
        混着写，还标成本地引用——这是最坏的一种错误。
        """
        top_local = max((d.get("rerank_score") or 0 for d in ranked if d.get("source") == "local"), default=0)
        local_count = len(rrf_chunks)

        if is_fact_query:
            return ranked, True
        if local_count < 3 or top_local < 0.55:
            logger.info(f"本地覆盖不足（{local_count} 条，最高分 {top_local:.3f}），保留联网补位")
            return ranked, True

        kept = [d for d in ranked if d.get("source") == "local"]
        if len(kept) < len(ranked):
            logger.info(f"本地已覆盖（{local_count} 条，最高分 {top_local:.3f}），丢弃联网结果")
        return kept, False

    # ------------------------------------------------------------------

    @staticmethod
    def normalize(rrf_chunks: list, web_docs: list) -> list[dict]:
        merged: list[dict] = []
        for chunk in rrf_chunks:
            breadcrumb = chunk.get("breadcrumb") or ""
            title = chunk.get("title") or ""
            display_title = f"{breadcrumb} > {title}" if breadcrumb and breadcrumb != title else title
            merged.append({
                "title": display_title,
                "content": chunk.get("content") or "",
                "url": chunk.get("url") or "",
                "score": chunk.get("score") or 0,
                "source": "local",
                "city_display": chunk.get("city_display") or "",
                "content_type": chunk.get("content_type") or "",
                "entity_name": chunk.get("entity_name") or "",
                "doc_title": chunk.get("doc_title") or "",
                "source_file": chunk.get("source_file") or "",
                "source_path": chunk.get("source_path") or "",
            })

        for doc in web_docs:
            merged.append({
                "title": doc.get("title") or "",
                "content": doc.get("content") or "",
                "url": doc.get("url") or "",
                "score": doc.get("score") or 0,
                "source": "web",
                "city_display": "",
                "content_type": "",
                "entity_name": "",
                "doc_title": "",
                "source_file": "",
                "source_path": "",
            })
        return merged

    @staticmethod
    def rerank(query: str, merged: list[dict]) -> list[dict]:
        try:
            res = text_rerank(
                query=query,
                texts=[doc.get("content") or "" for doc in merged],
                limit=len(merged),
            )
            for item in res:
                idx = item.get("index")
                if idx is not None and 0 <= idx < len(merged):
                    merged[idx]["rerank_score"] = item.get("score")
        except Exception as e:
            logger.warning(f"重排序接口失败，退回按召回分数排序: {e}")

        for doc in merged:
            if doc.get("rerank_score") is None:
                doc["rerank_score"] = doc.get("score") or 0

        return sorted(merged, key=lambda x: x["rerank_score"], reverse=True)

    @staticmethod
    def apply_web_penalty(ranked: list[dict], is_fact_query: bool) -> list[dict]:
        if is_fact_query:
            return ranked
        penalty = TourismConfig.web_penalty
        for doc in ranked:
            if doc.get("source") == "web":
                doc["rerank_score"] = doc["rerank_score"] * penalty
        return sorted(ranked, key=lambda x: x["rerank_score"], reverse=True)

    @staticmethod
    def cut_by_cliff(ranked: list[dict]) -> list[dict]:
        if not ranked:
            return []

        use_max = min(RERANK_MAX_TOPK, len(ranked))
        break_idx = use_max

        for i in range(use_max - 1):
            current = ranked[i].get("rerank_score") or 0
            nxt = ranked[i + 1].get("rerank_score") or 0
            abs_gap = current - nxt
            rel_gap = abs_gap / (current + 1e-6)
            if rel_gap > RERANK_GAP_RATIO or abs_gap > RERANK_GAP_ABS:
                break_idx = max(i + 1, min(RERANK_MIN_TOPK, use_max))
                break

        return ranked[:break_idx]
