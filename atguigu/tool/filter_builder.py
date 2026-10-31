"""
Milvus 过滤表达式构建 + 软过滤检索。

为什么要单独抽一个模块：
旅游场景的过滤维度是「城市 + 内容类型 + 实体」的组合，
两个检索节点（普通向量 / HyDE）都要用同一套表达式，
而且都要支持"过滤太严就自动放宽"的软过滤策略，所以统一放这里。
"""
from typing import Any

from atguigu.config.config import TourismConfig
from atguigu.tool.logger import logger
from atguigu.tool.milvus_client_tool import get_milvus_client, get_search_reqs, hybrid_search

# 过滤后少于这个条数，就认为过滤太严，自动放宽
MIN_RESULTS = 3


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def build_city_expr(city_tags: list[str] | None) -> str:
    """城市过滤：city_tags 是逗号拼接的字符串，用 like 做包含匹配。"""
    tags = [t for t in (city_tags or []) if t]
    if not tags:
        return ""
    clauses = [f'city_tags like "%{_escape(tag)}%"' for tag in tags]
    return "(" + " or ".join(clauses) + ")" if len(clauses) > 1 else clauses[0]


def build_content_type_expr(content_types: list[str] | None) -> str:
    types = [t for t in (content_types or []) if t]
    if not types:
        return ""
    quoted = ",".join(f'"{_escape(t)}"' for t in types)
    return f"content_type in [{quoted}]"


def build_entity_expr(entities: list[str] | None) -> str:
    names = [e for e in (entities or []) if e]
    if not names:
        return ""
    quoted = ",".join(f'"{_escape(n)}"' for n in names)
    return f"entity_name in [{quoted}]"


def build_expr_variants(
    city_tags: list[str] | None,
    content_types: list[str] | None,
    entities: list[str] | None = None,
) -> list[tuple[str, str | None]]:
    """
    生成从严格到宽松的过滤方案。

    返回 [(级别名, 表达式)]，按优先级排列：
      full       城市 + 内容类型 + 实体（最准）
      city_type  城市 + 内容类型（内容类型判断可能不准，比如"天涯海角门票"是景点介绍，
                 但"天涯海角怎么去"是交通指南，硬套类型会漏）
      city       只按城市
      none       不过滤（跨城市推荐 / 问题里没有城市）
    """
    city_expr = build_city_expr(city_tags)
    type_expr = build_content_type_expr(content_types)
    entity_expr = build_entity_expr(entities)

    variants: list[tuple[str, str | None]] = []
    if city_expr and type_expr and entity_expr:
        variants.append(("full", f"{city_expr} and {type_expr} and {entity_expr}"))
    if city_expr and type_expr:
        variants.append(("city_type", f"{city_expr} and {type_expr}"))
    if city_expr and entity_expr:
        variants.append(("city_entity", f"{city_expr} and {entity_expr}"))
    if city_expr:
        variants.append(("city", city_expr))
    variants.append(("none", None))
    return variants


def search_with_soft_filter(
    collection: str,
    dense_data: list,
    sparse_data: list,
    city_tags: list[str] | None,
    content_types: list[str] | None,
    entities: list[str] | None = None,
    limit: int | None = None,
    output_fields: list[str] | None = None,
    ranker: tuple = (0.6, 0.4),
    min_results: int = MIN_RESULTS,
) -> tuple[list[dict], str]:
    """
    带软过滤的混合检索：先按最严格的过滤查，结果太少就逐级放宽。

    返回 (命中列表, 实际生效的过滤级别)。
    """
    limit = limit or TourismConfig.search_limit
    output_fields = output_fields or [
        "id", "doc_id", "doc_title", "title", "breadcrumb", "content", "part",
        "content_type", "city", "city_tags", "city_display",
        "entity_name", "entity_type", "source_file", "source_path",
    ]

    last_hits: list[dict] = []
    for level, expr in build_expr_variants(city_tags, content_types, entities):
        try:
            reqs = get_search_reqs(
                dense_data=dense_data,
                sparse_data=sparse_data,
                dense_anns_field="dense_vector",
                sparse_anns_field="sparse_vector",
                limit=limit,
                expr=expr,
            )
            res = hybrid_search(
                collection_name=collection,
                reqs=reqs,
                limit=limit,
                output_fields=output_fields,
                ranker=ranker,
            )
        except Exception as e:
            logger.warning(f"检索失败(level={level}, expr={expr}): {e}")
            continue

        hits = res[0] if res else []
        if hits:
            last_hits = hits
        if len(hits) >= min_results:
            if level != "full":
                logger.info(f"过滤放宽到 {level}（expr={expr}），命中 {len(hits)} 条")
            return hits, level

    return last_hits, "none"


def count_rows(collection: str) -> int:
    """
    统计集合行数。

    注意：Milvus 的 get_collection_stats 在数据未 flush 时会返回 0，
    所以这里用 count(*) 查询，更可靠。
    """
    try:
        client = get_milvus_client()
        res = client.query(collection_name=collection, filter="id >= 0", output_fields=["count(*)"])
        return int(res[0]["count(*)"]) if res else 0
    except Exception as e:
        logger.warning(f"统计 {collection} 行数失败: {e}")
        return -1


def to_chunk(hit: dict[str, Any], source: str = "local") -> dict[str, Any]:
    """
    把 Milvus 的命中结果拍平成便于后续处理的 chunk 字典。

    注意：主键 id 在 hit 的**顶层**（`{"id":..., "distance":..., "entity":{...}}`），
    不在 entity 里。原实现直接 `{**entity}` 会把 id 丢掉，
    导致 RRF 按 id 去重时所有切片的 key 都是 None，全部塌缩成一条。
    这里显式把顶层 id 补回来。
    """
    entity = hit.get("entity") or {}
    return {
        "id": hit.get("id"),
        **entity,
        "score": hit.get("distance"),
        "source": source,
    }
