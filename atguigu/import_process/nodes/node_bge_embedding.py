from atguigu.import_process.base import NodeBase
from atguigu.import_process.state import ImportGraphState
from atguigu.tool.get_bge_embeddings import get_bge_embedding
from atguigu.tool.logger import logger

# 每批编码条数。原文是 3，这里放宽到 8：语料总量只有 5 万字符，
# 批大一点能少走几轮模型调用，显存占用仍然很低。
BATCH_SIZE = 8


class NodeBGEEmbedding(NodeBase):
    """
    混合向量化节点：用 BGE-M3 同时产出 dense + sparse 向量。

    与商品手册版本的差异：编码文本不再是「商品名 + 正文」，
    而是「城市 + 内容类型 + 章节路径 + 实体名 + 正文」。
    这样即使用户问的是"三亚有什么好玩的"这种不带实体名的问题，
    城市和类型信息也能参与相似度计算，召回更稳。
    """

    name = "node_bge_embedding"

    def process(self, state: ImportGraphState):
        chunks = state.get("chunks")
        if not chunks:
            logger.error("没有获取到 chunks，无法向量化")
            raise ValueError("没有获取到 chunks，无法向量化")

        for start in range(0, len(chunks), BATCH_SIZE):
            batch = chunks[start:start + BATCH_SIZE]
            texts = [self.build_embedding_text(chunk) for chunk in batch]
            embeddings = get_bge_embedding(texts)

            for idx, chunk in enumerate(batch):
                chunk["dense_vector"] = embeddings["dense"][idx]
                chunk["sparse_vector"] = embeddings["sparse"][idx]

        logger.info(f"向量化完成: {len(chunks)} 个切片")
        return {"chunks": chunks}

    @staticmethod
    def build_embedding_text(chunk: dict) -> str:
        """
        拼接参与向量化的文本。

        顺序刻意保持「城市 -> 类型 -> 章节 -> 实体 -> 正文」，
        让最重要的过滤维度出现在开头，稀疏向量（近似 BM25）更容易命中关键词。
        """
        parts = []
        city = chunk.get("city_display") or ""
        ctype = chunk.get("content_type") or ""
        breadcrumb = chunk.get("breadcrumb") or ""
        entity = chunk.get("entity_name") or ""
        title = chunk.get("title") or ""

        if city:
            parts.append(city)
        if ctype:
            parts.append(ctype)
        if breadcrumb:
            parts.append(breadcrumb)
        if entity and entity != title:
            parts.append(entity)
        if title:
            parts.append(title)

        header = "｜".join(parts)
        content = chunk.get("content") or ""
        return f"{header}\n{content}" if header else content
