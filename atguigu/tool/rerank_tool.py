import dashscope
from http import HTTPStatus

from atguigu.config.config import RerankConfig
from atguigu.tool.logger import logger
# 以下为华北2（北京）地域的配置，调用时请将{WorkspaceId}替换为真实的业务空间ID，各地域的配置不同。
dashscope.base_http_api_url = RerankConfig.rerank_base_url
dashscope.api_key = RerankConfig.rerank_api_key

def text_rerank(query,texts,limit=10):
    try:
        resp = dashscope.TextReRank.call(
            model="qwen3.7-text-rerank",
            query=query, # str
            documents=texts, # List[str]
            top_n=limit, # 需要断崖检测获取动态topk
            instruct="Given a web search query, retrieve relevant passages that answer the query."
        )
        # print(resp,type(resp))
        # 返回的是一个ReRankResponse对象,这个对象继承自dict,里面有status_code属性响应码，和output属性
        # print(resp.output, type(resp.output))
        # output属性值是一个RerankOutput属性，字典中有results键
        # print(resp.output.results, type(resp.output.results))
        # .results是一个列表，每个元素都是一个字典，里面包含relevance_score是rerank模型重新打的分
        if resp.status_code == HTTPStatus.OK:
            return [{"index":item.index,"score":item.relevance_score} for item in resp.output.results]
        else:
            logger.error(f"重排序请求失败")
            raise Exception(f"重排序请求失败")
    except Exception as e:
        logger.error(f"重排序请求失败，{e}")
        raise e


if __name__ == '__main__':
    text_rerank(query="我爱谁",texts=["我爱杨幂","我爱赵丽颖","我爱迪丽热巴"])