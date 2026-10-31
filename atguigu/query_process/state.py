# atguigu/query_process/state.py

from typing import TypedDict, List


class QueryGraphState(TypedDict, total=False):
    """
    查询链的图状态。

    与商品手册版本的差异：检索维度从「商品名」换成
    「城市 + 内容类型 + 实体」，并新增跨城推荐、事实型问题、引用信息等字段。
    """
    task_id: str            # 任务ID
    session_id: str         # 会话ID
    message_id: str         # 消息ID

    original_query: str     # 用户原始问题
    rewritten_query: str    # 改写后的问题

    # 检索意图（由 node_query_analyze 产出）
    cities: List[str]           # 城市标签，如 ['昆明','大理','丽江']
    city_display: str           # 城市展示名
    content_types: List[str]    # 目标内容类型，如 ['景点介绍']
    entities: List[str]         # 对齐后的实体名，如 ['亚龙湾']
    is_cross_city: bool         # 用户没指定城市，需要跨城市推荐
    is_fact_query: bool         # 是否在问价格/开放时间/电话这类事实字段
    filter_used: str            # 实际生效的过滤级别，便于排查

    # 检索过程中的中间数据
    embedding_chunks: list      # 普通向量检索结果
    hyde_embedding_chunks: list # HyDE 检索结果
    web_search_docs: list       # 联网搜索结果

    # 排序过程中的数据
    rrf_chunks: list            # RRF 融合后的切片
    reranked_docs: list         # 重排后的最终 Top-K
    small_kb: bool              # 是否走了小库直通（跳过 RRF 加权）

    # 生成过程中的数据
    prompt: str                 # 组装好的 Prompt
    answer: str                 # 最终答案
    citations: list             # 引用信息（城市/类型/章节/文件/来源）

    # 辅助信息
    history: list               # 历史对话
