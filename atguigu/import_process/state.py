from typing import TypedDict


class ImportGraphState(TypedDict, total=False):
    """
    导入链的图状态。

    与商品手册版本的差异：元数据从单个 item_name 扩展为
    「城市 + 内容类型 + 实体」三个维度，且全部来自文档自带的 `## 元数据` 块，
    由 node_metadata_parse 用正则解析，不再调用大模型识别。
    """

    task_id: str            # 任务唯一ID，用于进度追踪

    # 流程控制标记
    is_md_read_enabled: bool    # 是否启用 md 读取路径
    is_pdf_read_enabled: bool   # 是否启用 pdf 读取路径（旅游语料全是 md，保留兼容）

    # 路径相关
    local_dir: str          # 输出目录
    local_file_path: str    # 原始输入文件绝对路径
    file_title: str         # 文件名去后缀
    pdf_path: str           # pdf 文件路径
    md_path: str            # Markdown 文件路径

    # 文档级元数据（由 node_metadata_parse 产出）
    doc_id: str             # 文档唯一标识（source_path 的短哈希），用于幂等覆盖
    source_file: str        # 来源文件名，如「三亚景点推荐.md」
    source_path: str        # 来源相对路径，如「景点攻略/三亚景点推荐.md」
    doc_title: str          # 文档主标题（H1）
    content_type: str       # 标准内容类型：景点介绍/线路推荐/酒店信息/美食推荐/交通指南
    city_tags: list         # 城市标签列表，如 ['昆明','大理','丽江']
    city_display: str       # 城市展示名，如「云南（昆明、大理、丽江）」
    topic: str              # 元数据里的「主题」
    entity_names: list      # 文档涉及的实体名（景点/酒店/餐厅/片区）

    # 内容数据
    md_content: str         # md 全文
    chunks: list            # 切片列表（每条都带完整元数据）
    embeddings_content: list
