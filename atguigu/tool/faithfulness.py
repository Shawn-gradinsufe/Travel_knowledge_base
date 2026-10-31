"""
答案忠实度校验。

为什么需要这一层：
提示词里已经写了「禁止出现参考内容里没有的专有名词」，但实测模型依然会补——
问大理三天怎么玩，答案里冒出「凤阳邑村」「龙龛码头」「桃源S湾」；
问鼓浪屿怎么去，冒出「三丘田码头」「内厝澳码头」「东渡狐尾山」。
这些地点真实存在，但**知识库里一个字都没有**，属于典型的"合理但无依据"。

纯靠提示词约束不住，所以加一层生成后校验：
把答案里的地名候选逐个回查整个语料库，凡是语料里找不到的，
带着禁用词清单让模型重写一次（只重写一次，不循环）。
"""
import re
from pathlib import Path

from atguigu.tool.logger import logger

# 地点后缀（按长度倒序匹配，先匹配"古镇"再匹配"镇"这类）
PLACE_SUFFIXES = ["古镇", "古城", "码头", "街区", "海滩", "广场", "公园", "博物院", "博物馆",
                  "村", "寺", "山", "湖", "岛", "湾"]

# 候选词里不该出现的字符（标点、连词、方位词等），出现就说明切错了
NOISE_CHARS = set("，。、；：！？（）()【】「」“”\"' \n\t+·&/的了吗呢吧啊是在从到前往至和与及经过"
                  "去回是把被让就也都还又并或如若可能需要先再后间时日点该此各每某所以于为对向"
                  "朝沿顺绕穿越入进出上下内外中前里旁等")

# 通用的修饰性名称部分，不算专有名词
GENERIC_NAME_PARTS = {"小众", "大型", "小型", "传统", "著名", "主要", "其他", "周边",
                      "附近", "当地", "各个", "特色", "热门", "经典", "临湖", "环湖",
                      "沿湖", "临海", "面海", "靠山"}

# 名称部分里出现这些动作/描述字，基本不可能是地名
# （能挡掉"顺利登岛"被切成"利登岛"、"远眺山"被切成"远眺山"这类误判）
ACTION_CHARS = set("登达抵离靠临眺观览赏游逛住吃喝")

_corpus_cache: str | None = None


def load_corpus(data_root: str | None = None) -> str:
    """加载整个语料库（去掉空白），用于判断专有名词是否有依据。进程内缓存一次。"""
    global _corpus_cache
    if _corpus_cache is not None:
        return _corpus_cache

    from atguigu.config.config import TourismConfig

    root = Path(data_root or TourismConfig.data_root)
    if not root.exists():
        logger.warning(f"语料根目录不存在，跳过忠实度校验: {root}")
        _corpus_cache = ""
        return ""

    parts = [p.read_text(encoding="utf-8") for p in root.rglob("*.md")]
    _corpus_cache = "".join(parts).replace(" ", "").replace("\n", "").replace("\t", "")
    logger.info(f"忠实度校验语料已加载: {len(parts)} 个文件 / {len(_corpus_cache)} 字符")
    return _corpus_cache


def find_unknown_terms(answer: str, corpus: str | None = None, min_name_chars: int = 2) -> list[str]:
    """
    找出答案里"知识库中不存在"的地名候选。

    做法：定位每个地点后缀，向前回溯组成候选名（如「龙龛」+「码头」），
    只要存在任意一个候选在语料库里出现过，就认为这个名字有依据；
    全都没出现则判定为编造。

    只报"名字部分至少 min_name_chars 个字"的候选，避免把「码头」这种通用词报出来。
    """
    corpus = corpus if corpus is not None else load_corpus()
    if not corpus or not answer:
        return []

    body = answer.split("【参考来源】")[0]
    unknown: list[str] = []

    for suffix in PLACE_SUFFIXES:
        for match in re.finditer(re.escape(suffix), body):
            end = match.end()
            grounded = False
            candidates: list[str] = []

            # 从短到长回溯，名称部分取 2~4 个字
            for extra in range(2, 5):
                start = end - len(suffix) - extra
                if start < 0:
                    break
                cand = body[start:end]
                if NOISE_CHARS & set(cand):
                    continue
                name_part = cand[:-len(suffix)]
                if name_part in GENERIC_NAME_PARTS:
                    continue
                if ACTION_CHARS & set(name_part):
                    continue
                candidates.append(cand)
                # 完整候选 或 名称部分本身 在语料里出现过，都算有依据
                # （"喜洲古镇"整个词不在语料里，但"喜洲"在，就不该判定为编造）
                if cand in corpus or name_part in corpus:
                    grounded = True
                    break

            if grounded or not candidates:
                continue

            # 取名字部分最长的候选作为报告对象（可读性最好）
            unknown.append(candidates[-1])

    # 去重并剔除互为子串的冗余项
    unique = sorted(set(unknown), key=len, reverse=True)
    result: list[str] = []
    for term in unique:
        if not any(term in kept for kept in result):
            result.append(term)
    return result


def build_rewrite_prompt(answer: str, unknown_terms: list[str]) -> str:
    terms = "、".join(unknown_terms)
    return f"""下面这段旅游问答的回答里，出现了这些**知识库中并不存在**的地名：{terms}

请改写这段回答，要求：
1. 删除或替换上面这些地名，改成不带具体地名的方向性表述（例如"可以再安排一段小众村落"）；
2. 不要引入任何新的专有名词（景点名、地名、店名、菜名都不行）；
3. 保留原有的段落结构和【编号】引用标记，编号含义不变；
4. 只输出改写后的正文，不要任何解释、不要加"改写后"之类的字样。

原文：
{answer}
"""
