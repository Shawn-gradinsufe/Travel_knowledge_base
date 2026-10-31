"""
旅游知识库导入链。

链路：
    入口分流 → (PDF 转 MD，仅 pdf 输入) → 元数据解析 → 文档切分
             → 实体抽取 → 双向量化 → 导入 Milvus

与商品手册版本的差异：
- 新增 `node_metadata_parse`（正则解析元数据）和 `node_entity_extract`（实体抽取）；
- 去掉 `node_item_name_recognition`（商品名识别，教育/旅游场景都不需要）；
- 去掉 `node_md_img`（旅游语料 0 张图片，图片理解节点在本项目中空转，故不挂载）。
"""
from pathlib import Path

from langgraph.constants import END, START
from langgraph.graph import StateGraph

from atguigu.config.config import TourismConfig
from atguigu.import_process.nodes.node_bge_embedding import NodeBGEEmbedding
from atguigu.import_process.nodes.node_document_split import NodeDocumentSplit
from atguigu.import_process.nodes.node_entity_extract import NodeEntityExtract
from atguigu.import_process.nodes.node_entry import NodeEntry
from atguigu.import_process.nodes.node_import_milvus import NodeImportMilvus
from atguigu.import_process.nodes.node_metadata_parse import NodeMetadataParse
from atguigu.import_process.nodes.node_pdf_to_md import NodePDFToMD
from atguigu.import_process.state import ImportGraphState
from atguigu.tool.json_format import json_format
from atguigu.tool.logger import logger


class MainGraphRunner:
    def __init__(self):
        self.builder = StateGraph(state_schema=ImportGraphState)
        self.add_nodes()
        self.add_edges()
        self.graph = None

    def add_nodes(self):
        self.builder.add_node(NodeEntry.name, NodeEntry())
        self.builder.add_node(NodePDFToMD.name, NodePDFToMD())
        self.builder.add_node(NodeMetadataParse.name, NodeMetadataParse())
        self.builder.add_node(NodeDocumentSplit.name, NodeDocumentSplit())
        self.builder.add_node(NodeEntityExtract.name, NodeEntityExtract())
        self.builder.add_node(NodeBGEEmbedding.name, NodeBGEEmbedding())
        self.builder.add_node(NodeImportMilvus.name, NodeImportMilvus())

    def after_entry_router(self, state: ImportGraphState):
        if state.get("is_pdf_read_enabled"):
            return NodePDFToMD.name
        if state.get("is_md_read_enabled"):
            return NodeMetadataParse.name
        return END

    def add_edges(self):
        self.builder.add_edge(START, NodeEntry.name)
        self.builder.add_conditional_edges(NodeEntry.name, self.after_entry_router)
        self.builder.add_edge(NodePDFToMD.name, NodeMetadataParse.name)
        self.builder.add_edge(NodeMetadataParse.name, NodeDocumentSplit.name)
        self.builder.add_edge(NodeDocumentSplit.name, NodeEntityExtract.name)
        self.builder.add_edge(NodeEntityExtract.name, NodeBGEEmbedding.name)
        self.builder.add_edge(NodeBGEEmbedding.name, NodeImportMilvus.name)
        self.builder.add_edge(NodeImportMilvus.name, END)

    def run(self, state):
        # 懒加载 + 复用已编译图，避免重复编译
        if self.graph is None:
            self.graph = self.builder.compile()
        return self.graph.invoke(state)

    @classmethod
    def create_and_run(cls, state):
        return cls().run(state)


def iter_corpus_files(data_root: str | None = None) -> list[Path]:
    """遍历语料目录，返回所有待导入的 md 文件（按路径排序，保证顺序稳定）。"""
    root = Path(data_root or TourismConfig.data_root)
    if not root.exists():
        raise FileNotFoundError(f"语料根目录不存在: {root}")
    files = sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in (".md", ".pdf"))
    return files


def run_batch(data_root: str | None = None, task_id: str = "batch") -> dict:
    """
    批量导入整个语料目录。

    单文件失败不中断整批：记录失败清单继续下一个，
    对应需求里的「避免导入失败导致服务整体不可用」。
    """
    files = iter_corpus_files(data_root)
    runner = MainGraphRunner()

    ok, failed = [], []
    for idx, path in enumerate(files, start=1):
        logger.info(f"[{idx}/{len(files)}] 开始导入 {path.name}")
        try:
            result = runner.run({
                "task_id": task_id,
                "local_file_path": str(path),
                "local_dir": str(path.parent),
            })
            ok.append({
                "file": path.name,
                "chunks": len(result.get("chunks") or []),
                "entities": len(result.get("entity_names") or []),
            })
        except Exception as e:
            logger.error(f"导入失败 {path.name}: {e}")
            failed.append({"file": path.name, "error": str(e)})

    logger.info(f"批量导入结束: 成功 {len(ok)}，失败 {len(failed)}")
    return {"total": len(files), "ok": ok, "failed": failed}


if __name__ == '__main__':
    summary = run_batch(task_id="tourism-batch")
    logger.info(json_format(summary))
