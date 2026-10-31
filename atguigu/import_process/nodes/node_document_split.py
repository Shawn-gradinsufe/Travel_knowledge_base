import re

from langchain_text_splitters import RecursiveCharacterTextSplitter

from atguigu.config.config import TourismConfig
from atguigu.import_process.base import NodeBase
from atguigu.import_process.state import ImportGraphState
from atguigu.tool.json_format import json_format
from atguigu.tool.logger import logger

CODE_FENCE_PATTERN = re.compile(r"^(`{3,}|~{3,})")
HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+?)\s*$")

# 不作为正文切片的结构性标题
SKIP_TITLES = {"元数据"}


class NodeDocumentSplit(NodeBase):
    """
    文档切分节点：按标题粗切 + 按长度细切，并为每个切片回填完整元数据。

    与商品手册版本的关键差异：
    1. 维护**标题栈**，为每个切片生成 `breadcrumb`（如「核心景点推荐 > 亚龙湾」），
       这样引用信息能精确到章节，而不用让大模型猜；
    2. 跳过 `## 元数据` 段（它是元数据，不是正文，混进向量库会污染检索）；
    3. 每条切片带上 doc_id / content_type / city_tags 等过滤维度。
    """

    name = "node_document_split"

    def process(self, state: ImportGraphState):
        md_content = self._get_md_content(state)

        sections = self.get_split_section_list(md_content)
        chunks = self.get_final_chunk_list(sections, state)

        if not chunks:
            logger.error("切分后没有任何切片")
            raise ValueError("切分后没有任何切片")

        logger.info(
            f"切分完成: {state.get('source_path')} -> {len(sections)} 个章节 / {len(chunks)} 个切片"
        )
        return {"chunks": chunks}

    # ------------------------------------------------------------------
    # 细切
    # ------------------------------------------------------------------

    def get_final_chunk_list(self, sections: list[dict], state: ImportGraphState) -> list[dict]:
        splitter = RecursiveCharacterTextSplitter(
            separators=["\n\n", "\n", "。", "！", "？", "；", "!", "?", ";", " "],
            chunk_size=TourismConfig.chunk_size,
            chunk_overlap=TourismConfig.chunk_overlap,
        )

        # 所有切片共享的文档级元数据
        doc_meta = {
            "doc_id": state.get("doc_id"),
            "doc_title": state.get("doc_title"),
            "content_type": state.get("content_type"),
            "city_tags": state.get("city_tags") or [],
            "city_display": state.get("city_display"),
            "topic": state.get("topic", ""),
            "source_file": state.get("source_file"),
            "source_path": state.get("source_path"),
        }

        chunks: list[dict] = []
        for section in sections:
            title = section["title"]
            content = section["content"]
            if not content:
                continue

            # 短段落或含表格的段落整块保留，不再细切（避免把表格拆散）
            if len(content) < TourismConfig.chunk_size or "<table" in content:
                chunks.append({
                    **doc_meta,
                    "title": title,
                    "level": section["level"],
                    "breadcrumb": section["breadcrumb"],
                    "content": content,
                    "part": 0,
                })
                continue

            for idx, split_text in enumerate(splitter.split_text(content)):
                split_text = split_text.strip()
                if not split_text:
                    continue
                chunks.append({
                    **doc_meta,
                    "title": title,
                    "level": section["level"],
                    "breadcrumb": section["breadcrumb"],
                    "content": split_text,
                    "part": idx,
                })
        return chunks

    # ------------------------------------------------------------------
    # 粗切：按标题分节
    # ------------------------------------------------------------------

    def get_split_section_list(self, md_content: str) -> list[dict]:
        """
        按 Markdown 标题把全文切成章节。

        用状态机跟踪代码围栏，避免把围栏里的 `# 注释` 误判成标题；
        同时维护标题栈，为每个章节生成面包屑。
        """
        lines = md_content.split("\n")

        is_block = False
        marker = None
        stack: list[tuple[int, str]] = []      # [(level, text)]
        sections: list[dict] = []
        current: dict | None = None

        def close_section():
            nonlocal current
            if current is not None:
                body = "\n".join(current.pop("lines")).strip()
                if body:
                    current["content"] = body
                    sections.append(current)
            current = None

        for raw_line in lines:
            line = raw_line.strip()

            # --- 代码围栏状态机 ---
            fence = CODE_FENCE_PATTERN.match(line)
            if fence:
                if not is_block:
                    is_block = True
                    marker = fence.group(1)[0]
                elif marker == fence.group(1)[0]:
                    is_block = False
                    marker = None
                if current is not None:
                    current["lines"].append(raw_line)
                continue

            # --- 标题 ---
            if not is_block:
                heading = HEADING_PATTERN.match(line)
                if heading:
                    level = len(heading.group(1))
                    text = heading.group(2).strip()

                    # 弹栈到当前层级之上
                    while stack and stack[-1][0] >= level:
                        stack.pop()
                    stack.append((level, text))

                    close_section()

                    # H1 是文档标题，不单独成节；H2 及以下才切
                    if level >= 2:
                        breadcrumb = " > ".join(
                            t for lv, t in stack[:-1] if lv >= 2
                        )
                        current = {
                            "title": text,
                            "level": level,
                            "breadcrumb": breadcrumb,
                            "lines": [],
                        }
                    continue

            if current is not None:
                current["lines"].append(raw_line)

        close_section()

        # 去掉元数据段：它是元信息，不是正文
        sections = [s for s in sections if s["title"] not in SKIP_TITLES]
        return sections

    def _get_md_content(self, state: ImportGraphState) -> str:
        from pathlib import Path

        md_path = state.get("md_path")
        if not md_path:
            logger.error("未提供 md 文件路径")
            raise ValueError("未提供文件路径")

        md_path_obj = Path(md_path)
        if not md_path_obj.exists():
            logger.error(f"文件不存在: {md_path}")
            raise FileNotFoundError(f"文件不存在: {md_path}")

        with open(md_path_obj, "r", encoding="utf-8") as f:
            content = f.read()
        return content.replace("\r\n", "\n").replace("\r", "\n")


if __name__ == '__main__':
    from pathlib import Path

    node = NodeDocumentSplit()
    root = Path(TourismConfig.data_root)
    target = root / "景点攻略" / "三亚景点推荐.md"
    result = node({
        "md_path": str(target),
        "file_title": target.stem,
        "doc_id": "test",
        "doc_title": "三亚景点推荐",
        "content_type": "景点介绍",
        "city_tags": ["三亚"],
        "city_display": "三亚",
        "source_file": target.name,
        "source_path": "景点攻略/三亚景点推荐.md",
    })
    chunks = result["chunks"]
    logger.info(f"共 {len(chunks)} 个切片")
    for c in chunks[:6]:
        logger.info(f"[{c['breadcrumb'] or '-'} > {c['title']}] part={c['part']} len={len(c['content'])} :: {c['content'][:40]}")
