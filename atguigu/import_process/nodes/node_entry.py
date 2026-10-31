from pathlib import Path

from atguigu.config.config import TourismConfig
from atguigu.import_process.base import NodeBase
from atguigu.import_process.state import ImportGraphState
from atguigu.tool.logger import logger


class NodeEntry(NodeBase):
    """
    入口节点：校验文件并按类型分流。

    旅游语料全部是 Markdown（30 个 .md），所以主路径走 md；
    pdf 分支保留，方便后续接入 PDF 攻略。
    """

    name = "node_entry"

    def process(self, state: ImportGraphState):
        local_file_path = state.get("local_file_path")
        if not local_file_path:
            logger.error("文件路径未指定")
            raise Exception("文件路径未指定")

        path_obj = Path(local_file_path)
        if not path_obj.exists():
            logger.error(f"文件不存在: {local_file_path}")
            raise Exception(f"文件不存在: {local_file_path}")

        suffix = path_obj.suffix.lower()
        file_title = path_obj.stem

        # 来源相对路径：优先相对语料根目录，便于前端展示「景点攻略/三亚景点推荐.md」
        source_path = self._relative_source_path(path_obj)

        base = {
            "file_title": file_title,
            "source_file": path_obj.name,
            "source_path": source_path,
        }

        if suffix == ".md":
            return {**base, "md_path": str(path_obj), "is_md_read_enabled": True}
        if suffix == ".pdf":
            return {**base, "pdf_path": str(path_obj), "is_pdf_read_enabled": True}

        logger.error(f"不支持的文件类型: {suffix}")
        raise Exception(f"不支持的文件类型: {suffix}，只支持 .md / .pdf")

    @staticmethod
    def _relative_source_path(path_obj: Path) -> str:
        root = TourismConfig.data_root
        if root:
            try:
                return path_obj.resolve().relative_to(Path(root).resolve()).as_posix()
            except ValueError:
                pass
        return path_obj.name


if __name__ == '__main__':
    from atguigu.tool.json_format import json_format

    node = NodeEntry()
    root = Path(TourismConfig.data_root)
    result = node({"local_file_path": str(root / "景点攻略" / "三亚景点推荐.md")})
    logger.info(json_format(result))
