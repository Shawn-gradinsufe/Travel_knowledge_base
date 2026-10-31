"""
旅游知识库查询链路的端到端评测。

跑一组典型问题，把「意图解析结果 / 检索情况 / 引用 / 答案」落成 Markdown，
并做一次**数字落地检查**：答案里出现的金额、时间等数字，是否真的在参考内容里出现过。
这个检查专门用来抓"模型把联网内容或自身知识混进本地引用"的问题。
"""
import re
from pathlib import Path

from atguigu.query_process.main_graph import QueryMainGraphRunner
from atguigu.tool.faithfulness import find_unknown_terms, load_corpus
from atguigu.tool.task_utils import create_queue

QUESTIONS = [
    "三亚天涯海角门票多少钱",
    "带老人孩子适合去哪玩",
    "大理怎么玩三天",
    "亚龙湾值得住吗",
    "鼓浪屿怎么去",
    "成都有什么好吃的",
]

OUTPUT = Path("E:/Python_projects/RAG_review/.workbuddy-ai/eval_tourism.md")

# 需要核验的数字模式：金额、时间、距离
NUMBER_PATTERN = re.compile(r"\d+(?:\.\d+)?\s*(?:元|分钟|小时|公里|米|点|天|晚)")


def check_numbers(answer: str, context: str) -> list[str]:
    """答案里出现但参考内容里没有的数字，一律视为可疑（可能是编造）。"""
    suspicious = []
    for match in NUMBER_PATTERN.finditer(answer or ""):
        token = match.group(0).replace(" ", "")
        if token not in (context or "").replace(" ", ""):
            suspicious.append(token)
    return sorted(set(suspicious))


def check_places(answer: str, corpus: str) -> list[str]:
    """答案里的地名是否在整个语料库里存在过。判定逻辑与线上校验共用一套。"""
    return find_unknown_terms(answer, corpus)


def main():
    runner = QueryMainGraphRunner()
    corpus = load_corpus()
    lines = ["# 旅游知识库查询评测", ""]

    for idx, question in enumerate(QUESTIONS):
        task_id = f"eval-{idx}"
        create_queue(task_id)
        print(f"[{idx + 1}/{len(QUESTIONS)}] {question}")

        result = runner.run({
            "task_id": task_id,
            "session_id": f"eval_session_{idx}",
            "original_query": question,
        })

        docs = result.get("reranked_docs") or []
        local_docs = [d for d in docs if d.get("source") == "local"]
        web_docs = [d for d in docs if d.get("source") == "web"]
        # 数字核验时把标题也算进参考内容：像"第 3 天"这种数字只出现在章节标题里
        context = "\n".join(
            f"{d.get('title') or ''}\n{d.get('content') or ''}" for d in docs
        )
        answer = result.get("answer") or ""
        suspicious = check_numbers(answer, context)
        fake_places = check_places(answer, corpus)

        lines += [
            f"## {question}",
            "",
            f"- 城市：`{result.get('cities')}` → {result.get('city_display') or '（未识别）'}",
            f"- 内容类型：`{result.get('content_types')}`",
            f"- 实体：`{result.get('entities')}`",
            f"- 跨城推荐：`{result.get('is_cross_city')}`｜事实型：`{result.get('is_fact_query')}`",
            f"- 过滤级别：`{result.get('filter_used')}`｜小库直通：`{result.get('small_kb')}`",
            f"- 最终文档：本地 {len(local_docs)} 条 / 联网 {len(web_docs)} 条",
        ]
        removed = result.get("removed_terms") or []
        if removed:
            lines.append(f"- 忠实度重写：已移除无依据地名 `{removed}`")
        lines += [
            "",
            "**引用：**",
        ]
        for cite in result.get("citations") or []:
            if cite["source"] == "web":
                lines.append(f"- 【{cite['index']}】🌐 {cite['title'][:40]}（网络）")
            else:
                lines.append(
                    f"- 【{cite['index']}】{cite['city']}｜{cite['content_type']}｜{cite['title']}"
                )
        lines += ["", "**答案：**", "", "```", answer, "```", ""]
        if suspicious:
            lines += [f"> ⚠️ 可疑数字（参考内容中未出现）：{suspicious}", ""]
        if fake_places:
            lines += [f"> ⚠️ 可疑地名（整个语料库中都找不到）：{fake_places}", ""]
        if not suspicious and not fake_places:
            lines += ["> ✅ 落地检查通过（数字 + 地名）", ""]

        print(f"    本地 {len(local_docs)} / 联网 {len(web_docs)} | 可疑数字 {suspicious} | 可疑地名 {fake_places}")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n结果已写入 {OUTPUT}")


if __name__ == '__main__':
    main()
