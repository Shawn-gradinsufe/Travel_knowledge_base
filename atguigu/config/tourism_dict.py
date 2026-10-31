"""
旅游知识库的领域词典与归一化规则。

设计原则：
1. 城市、内容类型都是**封闭集**，用词典做规则匹配即可，不需要让大模型猜；
2. 数据里的城市取值不统一（有的写「云南多城市」，有的写「昆明、大理、丽江」），
   统一归一化成一组可过滤的标签（city_tags）；
3. 别名词典负责把用户口语（"亚龙湾""昆大丽"）映射到这些标签上。
"""

# ============================================================
# 城市
# ============================================================

# 数据里实际出现的城市标签（来自 30 个文档的元数据块）
# 注意：云南的 5 个文档打的是「昆明 / 大理 / 丽江」三个标签，不是「云南」
CITY_TAGS = ["三亚", "昆明", "大理", "丽江", "厦门", "张家界", "成都", "杭州", "乌镇"]

# 展示用的归属省份/大区，用于引用信息里给用户看
CITY_GROUP = {
    "三亚": "海南",
    "昆明": "云南",
    "大理": "云南",
    "丽江": "云南",
    "厦门": "福建",
    "张家界": "湖南",
    "成都": "四川",
    "杭州": "浙江",
    "乌镇": "浙江",
}

# 别名 -> 城市标签列表（一个别名可能对应多个标签，比如"云南"对应三个城市）
CITY_ALIAS = {
    # 三亚及其片区/景点
    "三亚": ["三亚"],
    "鹿城": ["三亚"],
    "亚龙湾": ["三亚"],
    "海棠湾": ["三亚"],
    "大东海": ["三亚"],
    "三亚湾": ["三亚"],
    "蜈支洲岛": ["三亚"],
    "蜈支洲": ["三亚"],
    "天涯海角": ["三亚"],
    "南山": ["三亚"],
    "鹿回头": ["三亚"],
    "西岛": ["三亚"],
    # 云南（多城市）
    "云南": ["昆明", "大理", "丽江"],
    "昆大丽": ["昆明", "大理", "丽江"],
    "昆明": ["昆明"],
    "大理": ["大理"],
    "洱海": ["大理"],
    "丽江": ["丽江"],
    "玉龙雪山": ["丽江"],
    "西双版纳": ["昆明", "大理", "丽江"],
    # 厦门
    "厦门": ["厦门"],
    "鼓浪屿": ["厦门"],
    "曾厝垵": ["厦门"],
    "环岛路": ["厦门"],
    # 张家界
    "张家界": ["张家界"],
    "武陵源": ["张家界"],
    "天门山": ["张家界"],
    "张家界国家森林公园": ["张家界"],
    # 成都
    "成都": ["成都"],
    "熊猫基地": ["成都"],
    "都江堰": ["成都"],
    "宽窄巷子": ["成都"],
    # 杭州
    "杭州": ["杭州"],
    "西湖": ["杭州"],
    "灵隐": ["杭州"],
    "灵隐寺": ["杭州"],
    "龙井": ["杭州"],
    "乌镇": ["乌镇"],
}

# 用于从文本里做最长优先匹配的别名列表（按长度倒序，避免"三亚湾"被"三亚"先吃掉）
CITY_ALIAS_KEYS = sorted(CITY_ALIAS.keys(), key=len, reverse=True)


# ============================================================
# 内容类型
# ============================================================

# 需求里规定的六类（文化民俗在数据中暂无样本，保留枚举位）
CONTENT_TYPES = ["景点介绍", "线路推荐", "酒店信息", "美食推荐", "交通指南", "文化民俗"]

# 数据里的原始写法 / 目录名 -> 标准内容类型
CONTENT_TYPE_ALIAS = {
    "景点介绍": "景点介绍",
    "景点攻略": "景点介绍",
    "景点推荐": "景点介绍",
    "景点": "景点介绍",
    "线路推荐": "线路推荐",
    "线路": "线路推荐",
    "路线": "线路推荐",
    "行程": "线路推荐",
    "酒店信息": "酒店信息",
    "住宿推荐": "酒店信息",
    "住宿": "酒店信息",
    "酒店": "酒店信息",
    "美食推荐": "美食推荐",
    "美食介绍": "美食推荐",   # 数据实际写的是"美食介绍"
    "美食": "美食推荐",
    "交通指南": "交通指南",
    "交通": "交通指南",
    "文化民俗": "文化民俗",
}

# 问题里的关键词 -> 候选内容类型（按优先级排列，允许多选）
# 这些是"软过滤"用的：命中就加过滤，没命中就不过滤
CONTENT_TYPE_KEYWORDS = [
    ("酒店信息", ["住哪", "住宿", "酒店", "民宿", "客栈", "住哪里", "住哪好", "房间", "住"]),
    ("美食推荐", ["吃", "美食", "餐厅", "小吃", "夜市", "海鲜", "菜", "馆子", "好吃"]),
    ("交通指南", ["怎么去", "怎么走", "交通", "机场", "高铁", "地铁", "轮渡", "包车", "自驾", "打车", "接驳", "换乘"]),
    ("线路推荐", ["行程", "几天", "几日", "线路", "路线", "怎么玩", "安排", "规划", "攻略顺序"]),
    ("景点介绍", ["景点", "好玩", "必去", "门票", "开放时间", "值得去", "打卡", "景区", "推荐去哪"]),
]


# ============================================================
# 事实型关键词
# ============================================================

# 命中这些词，说明用户在问"具体事实"（价格、时间、电话这类）。
# 这类字段在本知识库里几乎不存在（实测：开放时间 0 次、门票 2 次、无任何金额），
# 所以一旦命中且本地召回没有对应数字，就要走联网补位，并在答案里标注来源。
FACT_KEYWORDS = [
    "门票", "票价", "价格", "多少钱", "费用", "收费", "开放时间", "营业时间",
    "几点开门", "几点关门", "电话", "地址", "预约", "人均", "优惠", "学生票",
    "免票", "免费", "停车", "闭馆", "周一闭馆",
]


def match_cities(text: str) -> list[str]:
    """从文本里匹配城市标签（最长优先，去重保序）。"""
    if not text:
        return []
    hit: list[str] = []
    for alias in CITY_ALIAS_KEYS:
        if alias in text:
            for tag in CITY_ALIAS[alias]:
                if tag not in hit:
                    hit.append(tag)
            # 已命中的别名对应的文本片段做个简单遮蔽，避免短别名重复命中
            text = text.replace(alias, "\u3000" * len(alias))
    return hit


def match_content_types(text: str) -> list[str]:
    """从问题里推断候选内容类型（软过滤用，可能返回多个）。"""
    if not text:
        return []
    result: list[str] = []
    for ctype, keywords in CONTENT_TYPE_KEYWORDS:
        if any(kw in text for kw in keywords) and ctype not in result:
            result.append(ctype)
    return result


def has_fact_keyword(text: str) -> bool:
    """判断问题是否在问具体事实字段（价格/时间/电话等）。"""
    return bool(text) and any(kw in text for kw in FACT_KEYWORDS)


def normalize_content_type(raw: str | None, fallback: str | None = None) -> str:
    """把原始写法归一化成标准内容类型。"""
    for candidate in (raw, fallback):
        if not candidate:
            continue
        candidate = candidate.strip()
        if candidate in CONTENT_TYPE_ALIAS:
            return CONTENT_TYPE_ALIAS[candidate]
        for key, value in CONTENT_TYPE_ALIAS.items():
            if key in candidate:
                return value
    return "景点介绍"


def normalize_cities(raw_city: str | None, raw_dest: str | None = None, fallback_dir: str | None = None) -> list[str]:
    """
    把元数据里的城市字段归一化成城市标签列表。

    数据里的坑：
      - 交通/景点/酒店/美食 写的是「城市：云南多城市」
      - 线路 写的是「目的地：昆明、大理、丽江」
      - 杭州线路写的是「目的地：杭州、乌镇」
    所以先按分隔符拆，再逐个查词典，最后用目录名兜底。
    """
    tags: list[str] = []

    def _absorb(value: str | None):
        if not value:
            return
        value = value.strip()
        # 「云南多城市」这类写法直接按别名展开
        if "多城市" in value or "多地" in value:
            value = value.replace("多城市", "").replace("多地", "")
        # 先按常见分隔符拆
        parts = [p for p in value.replace("、", ",").replace("，", ",").replace("/", ",").replace(" ", ",").split(",") if p]
        for part in parts or [value]:
            part = part.strip()
            if not part:
                continue
            if part in CITY_ALIAS:
                for tag in CITY_ALIAS[part]:
                    if tag not in tags:
                        tags.append(tag)
            else:
                for tag in match_cities(part):
                    if tag not in tags:
                        tags.append(tag)

    _absorb(raw_city)
    if not tags:
        _absorb(raw_dest)
    if not tags and fallback_dir:
        _absorb(fallback_dir)
    return tags


def display_city(city_tags: list[str]) -> str:
    """把城市标签列表拼成给用户看的展示名，如 ['昆明','大理','丽江'] -> '云南（昆明、大理、丽江）'。"""
    if not city_tags:
        return ""
    groups: list[str] = []
    for tag in city_tags:
        group = CITY_GROUP.get(tag, tag)
        if group not in groups:
            groups.append(group)
    if len(groups) == 1 and len(city_tags) == 1:
        return city_tags[0]
    if len(city_tags) == 1:
        return f"{groups[0]}（{city_tags[0]}）"
    return f"{'、'.join(groups)}（{'、'.join(city_tags)}）"
