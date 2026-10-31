# atguigu/query_process/nodes/node_web_search_mcp.py
import asyncio
import json

from agents.mcp import MCPServerStreamableHttp
from atguigu.config.config import McpConfig
from atguigu.query_process.base import NodeBase
from atguigu.query_process.state import QueryGraphState
from atguigu.tool.json_format import json_format
from atguigu.tool.logger import logger

class NodeWebSearchMcp(NodeBase):
    """
    节点功能，调用外部搜索引擎补充信息
    """

    # 覆盖基类的 name 属性，标识节点名称
    name: str = "node_web_search_mcp"

    def process(self, state: QueryGraphState):
        """
        节点逻辑
        :param state: 工作流状态对象
        :return: 更新后的状态对象
        """

        rewritten_query = state.get("rewritten_query")
        if not rewritten_query:
            logger.error("改写后的用户问题不能为空")
            raise ValueError("改写后的用户问题不能为空")

        try:
            result = asyncio.run(self.mcp_run(rewritten_query))
            data = json.loads(result.content[0].text).get("pages") or []
        except Exception as e:
            # 联网搜索是"补位"能力，失败不能拖垮整条问答链路
            logger.warning(f"联网搜索失败，跳过该路召回: {e}")
            return {"web_search_docs": []}

        chunks = [
            {
                "title": item.get('title'),
                "content": item.get('snippet'),
                "url": item.get('url'),
                "source": "web"
            }
            for item in data
        ]
        logger.info(f"联网搜索: 命中 {len(chunks)} 条")
        return {
            "web_search_docs": chunks
        }

    async def mcp_run(self,query,limit=10) -> None:
        token = McpConfig.mcp_api_key
        async with MCPServerStreamableHttp(
                name="网络搜索mcp工具",
                params={
                    "url": McpConfig.mcp_base_url,
                    "headers": {"Authorization": f"Bearer {token}"},
                    "timeout": 10,
                },
                cache_tools_list=True,
                max_retry_attempts=3,
        ) as server:
            # 原本使用的是智能体的方式,现在没办法使用,只能调用服务器工具的方法传递工具名的方式去使用,异步操作
            result = await server.call_tool(
                tool_name="bailian_web_search", # 阿里云百炼联网搜索功能MCP工具的工具名称
                arguments={
                    "query": query,
                    "count": limit
                }
            )
            return result

if __name__ == "__main__":

    init_state = {
        "rewritten_query": "三亚天涯海角门票多少钱"
    }

    # 执行节点的业务调用
    node_web_search_mcp = NodeWebSearchMcp()
    result = node_web_search_mcp(init_state)
    logger.info(json_format(result))