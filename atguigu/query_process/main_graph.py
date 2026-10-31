"""
旅游知识库查询链。

链路：
    意图解析（城市/类型/实体）
        ├─ HyDE 检索 ─┐
        ├─ 普通检索 ──┼→ RRF 融合（小库直通）→ Rerank（本地优先）→ 答案生成（带引用）
        └─ 联网搜索 ──┘

与商品手册版本的差异：
- 「商品名确认」换成「意图解析」，识别不到城市时走跨城推荐而不是反问；
- 三路召回保留，但过滤条件改成城市/类型/实体组合，并支持过滤过严时自动放宽；
- 答案节点输出引用信息，区分本地与联网来源。
"""
from langgraph.constants import END
from langgraph.graph import StateGraph

from atguigu.query_process.nodes.node_answer_output import NodeAnswerOutput
from atguigu.query_process.nodes.node_query_analyze import NodeQueryAnalyze
from atguigu.query_process.nodes.node_rerank import NodeRerank
from atguigu.query_process.nodes.node_rrf import NodeRrf
from atguigu.query_process.nodes.node_search_embedding import NodeSearchEmbedding
from atguigu.query_process.nodes.node_search_embedding_hyde import NodeSearchEmbeddingHyde
from atguigu.query_process.nodes.node_web_search_mcp import NodeWebSearchMcp
from atguigu.query_process.state import QueryGraphState
from atguigu.tool.json_format import json_format
from atguigu.tool.logger import logger


class QueryMainGraphRunner:
    def __init__(self):
        self.builder = StateGraph(state_schema=QueryGraphState)
        self.add_nodes()
        self.add_edges()
        self.graph = None

    def add_nodes(self):
        self.builder.add_node(NodeQueryAnalyze.name, NodeQueryAnalyze())
        self.builder.add_node(NodeSearchEmbedding.name, NodeSearchEmbedding())
        self.builder.add_node(NodeSearchEmbeddingHyde.name, NodeSearchEmbeddingHyde())
        self.builder.add_node(NodeWebSearchMcp.name, NodeWebSearchMcp())
        self.builder.add_node(NodeRrf.name, NodeRrf())
        self.builder.add_node(NodeRerank.name, NodeRerank())
        self.builder.add_node(NodeAnswerOutput.name, NodeAnswerOutput())

    def after_analyze_router(self, state: QueryGraphState):
        # 意图解析阶段已经给出答案（例如参数缺失/无法识别），直接出结果
        if state.get("answer"):
            return NodeAnswerOutput.name
        return [
            NodeSearchEmbeddingHyde.name,
            NodeSearchEmbedding.name,
            NodeWebSearchMcp.name,
        ]

    def add_edges(self):
        self.builder.set_entry_point(NodeQueryAnalyze.name)
        self.builder.add_conditional_edges(NodeQueryAnalyze.name, self.after_analyze_router)
        self.builder.add_edge(NodeSearchEmbeddingHyde.name, NodeRrf.name)
        self.builder.add_edge(NodeSearchEmbedding.name, NodeRrf.name)
        self.builder.add_edge(NodeWebSearchMcp.name, NodeRrf.name)
        self.builder.add_edge(NodeRrf.name, NodeRerank.name)
        self.builder.add_edge(NodeRerank.name, NodeAnswerOutput.name)
        self.builder.add_edge(NodeAnswerOutput.name, END)

    def run(self, state):
        if self.graph is None:
            self.graph = self.builder.compile()
        return self.graph.invoke(state)

    @classmethod
    def create_and_run(cls, state):
        return cls().run(state)


if __name__ == '__main__':
    from atguigu.tool.task_utils import create_queue

    runner = QueryMainGraphRunner()
    questions = [
        "三亚天涯海角门票多少钱",
        "带老人孩子适合去哪玩",
        "大理怎么玩三天",
    ]
    for i, q in enumerate(questions):
        task_id = f"test-{i}"
        create_queue(task_id)
        result = runner.run({
            "task_id": task_id,
            "session_id": f"tour_demo_{i}",
            "original_query": q,
        })
        logger.info(f"=== {q} ===")
        logger.info(f"城市={result.get('cities')} 类型={result.get('content_types')} "
                    f"实体={result.get('entities')} 跨城={result.get('is_cross_city')}")
        logger.info(f"引用: {json_format(result.get('citations'))}")
        logger.info(f"答案: {(result.get('answer') or '')[:300]}")
