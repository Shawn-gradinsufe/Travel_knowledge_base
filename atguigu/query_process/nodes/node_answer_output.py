# atguigu/query_process/nodes/node_answer_output.py
import re

from atguigu.config.prompt import ANSWER_PROMPT
from atguigu.query_process.base import NodeBase
from atguigu.query_process.state import QueryGraphState
from atguigu.tool.faithfulness import build_rewrite_prompt, find_unknown_terms, load_corpus
from atguigu.tool.get_llm_model import get_item_llm_model
from atguigu.tool.logger import logger
from atguigu.tool.mongo_tool import save_chat_messages
from atguigu.tool.task_utils import put_data

# 没检索到内容时的兜底话术
NO_RESULT_ANSWER = (
    "知识库里没有检索到与这个问题相关的内容。\n\n"
    "可以换个说法，或者把目的地和想查的内容说得更具体一些，"
    "例如「三亚住哪个湾区比较方便」「大理三天怎么安排」。"
)


class NodeAnswerOutput(NodeBase):
    """
    答案生成节点。

    与商品手册版本的差异：
    1. 参考内容带编号和来源标记（local / web），提示词要求逐句标注引用；
    2. 生成完成后由**系统**追加【参考来源】区块，而不是让模型自己写，
       避免模型编造或漏写编号；
    3. 没有检索到内容时给出明确的兜底话术，而不是让模型硬答。
    """

    name: str = "node_answer_output"

    def process(self, state: QueryGraphState):
        task_id = state.get("task_id")
        docs = state.get("reranked_docs") or []
        history = state.get("history") or []
        entities = state.get("entities") or []
        rewritten_query = state.get("rewritten_query") or state.get("original_query") or ""

        # 意图解析阶段已经给出了答案（例如参数校验失败），直接推送
        preset = state.get("answer")
        if preset:
            put_data(task_id, event="final", data={"answer": preset, "citations": []})
            return {"answer": preset, "citations": []}

        if not docs:
            put_data(task_id, event="final", data={"answer": NO_RESULT_ANSWER, "citations": []})
            save_chat_messages(
                session_id=state.get("session_id"),
                role="assistant",
                text=NO_RESULT_ANSWER,
                rewritten_query=rewritten_query,
                item_names=entities,
            )
            return {"answer": NO_RESULT_ANSWER, "citations": []}

        citations = self.build_citations(docs)
        context = self.build_context(docs, citations, state)
        history_str = "\n".join(f"{h.get('role')}:{h.get('text')}" for h in history)

        prompt = ANSWER_PROMPT.format(
            question=rewritten_query,
            context=context,
            item_names=",".join(entities) if entities else "（未识别到具体实体）",
            history=history_str or "（无）",
        )
        if len(prompt) > 12000:
            prompt = prompt[:12000]

        answer = ""
        try:
            llm = get_item_llm_model()
            for chunk in llm.stream(input=[{"role": "user", "content": prompt}]):
                piece = chunk.content or ""
                if piece:
                    answer += piece
                    put_data(task_id, event="delta", data={"delta": piece})
        except Exception as e:
            logger.error(f"答案生成失败: {e}")
            answer = "生成答案时出错了，请稍后重试。如果反复失败，可以先把问题问得更具体一些。"

        # 生成后做一次忠实度校验：模型经常会补语料里没有的地名，
        # 发现就带着禁用词清单让它重写一次（只重写一次，不循环）。
        answer, removed_terms = self.enforce_faithfulness(answer, task_id)

        # 系统追加参考来源区块，保证编号与内容严格对应
        source_block = self.format_source_block(citations)
        if source_block and answer:
            answer += source_block
            put_data(task_id, event="delta", data={"delta": source_block})

        # 注意：final 里带的是**校验后的完整答案**，前端会用它对已经流式显示的内容做覆盖替换
        put_data(task_id, event="final", data={
            "answer": answer,
            "citations": citations,
            "removed_terms": removed_terms,
        })

        if answer:
            save_chat_messages(
                session_id=state.get("session_id"),
                role="assistant",
                text=answer,
                rewritten_query=rewritten_query,
                item_names=entities,
            )

        return {"answer": answer, "citations": citations, "prompt": prompt,
                "removed_terms": removed_terms}

    # ------------------------------------------------------------------

    @staticmethod
    def enforce_faithfulness(answer: str, task_id: str) -> tuple[str, list[str]]:
        """
        检查答案里有没有"知识库中不存在"的地名，有就让模型重写一次。

        返回 (可能被改写后的答案, 被判定为编造的词列表)。
        """
        if not answer:
            return answer, []

        try:
            corpus = load_corpus()
            unknown = find_unknown_terms(answer, corpus)
            if not unknown:
                return answer, []

            logger.warning(f"发现知识库中不存在的地名 {unknown}，触发重写")
            llm = get_item_llm_model()
            res = llm.invoke(input=[{
                "role": "user",
                "content": build_rewrite_prompt(answer, unknown),
            }])
            rewritten = (res.content or "").strip()
            if not rewritten:
                return answer, unknown

            still = find_unknown_terms(rewritten, corpus)
            if still:
                logger.warning(f"重写后仍有可疑地名: {still}")
            logger.info(f"忠实度重写完成，已移除 {len(unknown)} 个无依据地名")
            return rewritten, unknown
        except Exception as e:
            logger.warning(f"忠实度校验失败，保留原答案: {e}")
            return answer, []

    @staticmethod
    def build_citations(docs: list[dict]) -> list[dict]:
        citations = []
        for idx, doc in enumerate(docs, start=1):
            citations.append({
                "index": idx,
                "source": doc.get("source") or "local",
                "title": doc.get("title") or "",
                "city": doc.get("city_display") or "",
                "content_type": doc.get("content_type") or "",
                "source_file": doc.get("source_file") or "",
                "source_path": doc.get("source_path") or "",
                "url": doc.get("url") or "",
                "score": round(float(doc.get("rerank_score") or 0), 4),
            })
        return citations

    @staticmethod
    def build_context(docs: list[dict], citations: list[dict], state: QueryGraphState) -> str:
        lines = []
        if state.get("is_cross_city"):
            lines.append("（用户没有指定目的地，以下是跨城市的推荐，回答时要说明这一点）")
        if state.get("is_fact_query"):
            lines.append("（用户在问价格/开放时间这类具体事实，参考内容若没有明确数字，必须如实说明未收录）")

        for doc, cite in zip(docs, citations):
            head = (
                f"[切片:{cite['index']}] "
                f"[来源:{cite['source']}] "
                f"[城市:{cite['city'] or '-'}] "
                f"[类型:{cite['content_type'] or '-'}] "
                f"[章节:{cite['title'] or '-'}] "
                f"[文件:{cite['source_file'] or cite['title'] or '-'}]"
            )
            lines.append(head)
            lines.append(doc.get("content") or "")
            lines.append("")
        return "\n".join(lines)

    @staticmethod
    def format_source_block(citations: list[dict]) -> str:
        if not citations:
            return ""
        rows = ["", "", "【参考来源】"]
        for cite in citations:
            if cite["source"] == "web":
                rows.append(f"【{cite['index']}】{cite['title']}（网络）{cite['url']}")
            else:
                parts = [p for p in [cite["city"], cite["content_type"], cite["title"], cite["source_file"]] if p]
                rows.append(f"【{cite['index']}】" + "｜".join(parts))
        return "\n".join(rows)
