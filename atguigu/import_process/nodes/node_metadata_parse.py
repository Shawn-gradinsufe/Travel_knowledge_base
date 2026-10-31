import hashlib
import re
from pathlib import Path
from typing import Any

from atguigu.config.tourism_dict import (
    display_city,
    normalize_cities,
    normalize_content_type,
)
from atguigu.import_process.base import NodeBase
from atguigu.import_process.state import ImportGraphState
from atguigu.tool.json_format import json_format
from atguigu.tool.logger import logger

# 元数据块：`## 元数据` 之后到下一个二级标题之前
META_BLOCK_PATTERN = re.compile(r"^##\s*元数据\s*$([\s\S]*?)(?=^##\s)", re.M)
# 元数据条目：`- 键：值`
META_ITEM_PATTERN = re.compile(r"^-\s*([^：:]+)[：:]\s*(.*)$", re.M)
# 文档主标题
H1_PATTERN = re.compile(r"^#\s+(.+?)\s*$", re.M)

# 元数据里可能出现「名称」的键，按优先级取第一个非空值
NAME_KEYS = ["景点名称", "线路名称", "住宿名称", "文档名称", "餐厅名称", "酒店名称", "名称"]


class NodeMetadataParse(NodeBase):
    """
    元数据解析节点。

    旅游语料每个文档开头都有 `## 元数据` 块，字段名在各类目之间不统一
    （城市 / 目的地；景点名称 / 线路名称 / 住宿名称 / 文档名称），
    这里统一用正则解析 + 别名归一化，**不调用大模型**。

    归一化结果直接决定后续检索的过滤维度：
      - content_type：景点介绍 / 线路推荐 / 酒店信息 / 美食推荐 / 交通指南
      - city_tags：['昆明','大理','丽江'] 这种可过滤的标签列表
      - doc_id：由 source_path 派生，用于幂等覆盖
    """

    name = "node_metadata_parse"

    def process(self, state: ImportGraphState):
        md_path, md_content = self._read_md(state)

        meta = self._parse_meta_block(md_content)
        doc_title = self._parse_doc_title(md_content, state.get("file_title") or md_path.stem)

        # 目录名兜底：语料按 景点攻略/线路推荐/酒店信息/美食推荐/交通指南 分目录
        dir_name = self._dir_name(state, md_path)

        content_type = normalize_content_type(meta.get("内容类型"), dir_name)
        city_tags = normalize_cities(
            meta.get("城市"), meta.get("目的地"), fallback_dir=None
        )
        if not city_tags:
            # 元数据缺失时，用文件名兜底（文件名都带城市前缀，如「三亚景点推荐」）
            city_tags = normalize_cities(None, None, fallback_dir=state.get("file_title"))

        source_path = state.get("source_path") or md_path.name
        doc_id = hashlib.sha1(source_path.encode("utf-8")).hexdigest()[:16]

        result = {
            "doc_id": doc_id,
            "doc_title": doc_title,
            "content_type": content_type,
            "city_tags": city_tags,
            "city_display": display_city(city_tags),
            "topic": meta.get("主题", ""),
            "source_file": state.get("source_file") or md_path.name,
            "source_path": source_path,
        }

        if not city_tags:
            logger.warning(f"{source_path} 未能识别城市标签，检索时将不参与城市过滤")
        logger.info(
            f"元数据解析完成: {source_path} -> 类型={content_type} 城市={city_tags} 标题={doc_title}"
        )
        return result

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _read_md(self, state: ImportGraphState) -> tuple[Path, str]:
        md_path = state.get("md_path")
        if not md_path:
            logger.error("未找到 md 文件路径")
            raise ValueError("未找到 md 文件路径")

        md_path_obj = Path(md_path)
        if not md_path_obj.exists():
            logger.error(f"未找到 md 文件: {md_path}")
            raise ValueError(f"未找到 md 文件: {md_path}")

        with open(md_path_obj, "r", encoding="utf-8") as f:
            md_content = f.read()
        return md_path_obj, md_content.replace("\r\n", "\n").replace("\r", "\n")

    @staticmethod
    def _parse_meta_block(md_content: str) -> dict[str, Any]:
        match = META_BLOCK_PATTERN.search(md_content)
        if not match:
            return {}
        meta: dict[str, Any] = {}
        for key, value in META_ITEM_PATTERN.findall(match.group(1)):
            key = key.strip()
            value = value.strip()
            if key and value and key not in meta:
                meta[key] = value
        return meta

    @staticmethod
    def _parse_doc_title(md_content: str, fallback: str) -> str:
        match = H1_PATTERN.search(md_content)
        if match:
            title = match.group(1).strip()
            # 排除代码围栏里的 # 注释
            if title and not title.startswith("```"):
                return title
        return fallback

    @staticmethod
    def _dir_name(state: ImportGraphState, md_path: Path) -> str | None:
        """取语料一级目录名（景点攻略/线路推荐/...），用于内容类型兜底。"""
        source_path = state.get("source_path")
        if source_path and "/" in source_path:
            return source_path.split("/")[0]
        if md_path.parent.name:
            return md_path.parent.name
        return None


if __name__ == '__main__':
    from atguigu.config.config import TourismConfig

    node = NodeMetadataParse()
    root = Path(TourismConfig.data_root)
    for rel in ["景点攻略/三亚景点推荐.md", "线路推荐/云南线路推荐.md", "交通指南/杭州交通指南.md"]:
        target = root / rel
        result = node({
            "md_path": str(target),
            "file_title": target.stem,
            "source_file": target.name,
            "source_path": rel,
        })
        logger.info(json_format(result))
