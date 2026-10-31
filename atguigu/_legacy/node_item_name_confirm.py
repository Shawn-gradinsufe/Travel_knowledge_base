# atguigu/query_process/nodes/node_item_name_confirm.py

#导包规则：1、先导系统包 2、再导三方包 3、再导自定义包
import json
from typing import Any

from atguigu.config.config import MilvusConfig
from atguigu.config.prompt import ITEM_NAME_EXTRACT_SYSTEM_PROMPT, ITEM_NAME_EXTRACT_TEMPLATE
from atguigu.query_process.base import NodeBase
from atguigu.query_process.state import QueryGraphState
from atguigu.tool.get_bge_embeddings import get_bge_embedding
from atguigu.tool.get_llm_model import get_item_llm_model
from atguigu.tool.json_format import json_format
from atguigu.tool.logger import logger
from atguigu.tool.milvus_client_tool import get_search_reqs, hybrid_search
from atguigu.tool.mongo_tool import get_recent_messages, save_chat_messages, update_history_item_names
from atguigu.tool.task_utils import create_queue


class NodeItemNameConfirm(NodeBase):
    """
    节点功能：确认用户问题中的核心商品名称。
    """

    # 覆盖基类的 name 属性，标识节点名称
    name: str = "node_item_name_confirm"

    def process(self, state: QueryGraphState):
        """
        节点逻辑
        :param state: 工作流状态对象
        :return: 更新后的状态对象
        """
        # 1、获取state给的初始化数据，查询mongo拿到历史记录整理成字符串
        history_str, message_id, original_query, session_id = self.get_history_str(state)

        # 2、根据历史记录和原始问题，调用大模型提取商品名称和重写的问题,大模型做的意图识别,识别用户的问题是要做什么
        item_names, rewritten_query = self.get_item_names(history_str, original_query)

        # 3、向量化检索，遍历大模型得到识别的商品名称，一个一个去混合检索Milvus当中相似的item_names整理在列表
        # 初始化结果和答案
        final_item_names = []
        answer = "您问的商品暂时识别不到，请重新提问！"

        # 识别出来有名字再去进行向量化检索，然后名称对齐，否则没必要
        if item_names: # item_names的来源是大模型返回的答案
            # 对用户问题的商品进行向量化处理，得到embedding向量,拿着这个embedding去milvus里面去检索相似的商品名称
            search_item_name_list = self.hybrid_search_item_names(item_names)

            # 4、对齐商品名称，区分出确认的名字、可能的名字、噪音(最终的item_names保存在final_item_names中)

            answer, final_item_names = self.align_item_names(answer, final_item_names, search_item_name_list)

        # 5、处理历史记录，更新商品名称和重写问题到历史记录中
        message_id = self.handler_history(answer, final_item_names, message_id, rewritten_query, session_id)

        return {
            "message_id": message_id,
            "original_query": original_query,
            "answer":answer,
            "item_names":final_item_names,
            # 检索节点state中的item_names已经变成了意图识别的结果,是大模型识别出的结果经milvus中商品名称collection匹配后确认匹配的
            "rewritten_query": rewritten_query,
            "history": get_recent_messages(session_id) # 这里必须重新获取历史记录，否则拿的还是回填前的历史记录
        }

    def handler_history(self, answer: str, final_item_names: list[Any], message_id: Any | None, rewritten_query,
                        session_id: Any | None) -> Any | None:
        # 把商品名称对齐完成后，本节点主要功能已结束，但需要把历史记录处理一下
        if answer:  # 如果有答案，说明商品名称对齐成功了，要把历史记录处理一下
            # 保存该答案为历史记录
            message_id = save_chat_messages(
                session_id=session_id,
                role="assistant",
                text=answer
            )

        history_list = get_recent_messages(session_id)
        history_ids = [history.get('_id') for history in history_list]
        # 更新历史记录中的商品名称和重写问题
        update_history_item_names(ids=history_ids, item_names=final_item_names, rewritten_query=rewritten_query)
        return message_id

    def align_item_names(self, answer: str, final_item_names: list[Any], search_item_name_list: list[Any]) \
            -> tuple[str, list[Any]]: # 把检索整理的结果进行商品名称对齐:就是区分出确认的名字、可能的名字、噪音
        confirmed_item_names = [search_item_name.get("search_item_name")
                                for search_item_name in search_item_name_list
                                if search_item_name.get("score") >= 0.8]
        # 这里的confirmed_item_names是一个列表，里面是检索出来的商品名称，分数大于等于0.85的认为是确认的名字

        optional_item_names = [search_item_name.get("search_item_name")
                               for search_item_name in search_item_name_list
                               if 0.6 <= search_item_name.get("score") < 0.8]
        # 这里是分数在0.65到0.85之间的认为是可能的名字

        # noise = [search_item_name.get("original_item_name")
        #          for search_item_name in search_item_name_list
        #          if search_item_name.get("score") < 0.6

        if confirmed_item_names:
            # 有确定的名字
            final_item_names = confirmed_item_names
            answer = ''
        elif optional_item_names:
            final_item_names = []
            answer = f"请问您问的商品是{','.join(optional_item_names)}中的哪一个？"
        else:
            # 全是噪音，没有任何名字
            final_item_names = []
            answer = "您问的商品暂时识别不到，请重新提问！"
        return answer, final_item_names

    def hybrid_search_item_names(self, item_names: list[Any]) -> list[Any]:
        embeddings = get_bge_embedding(item_names)  # 返回的是一个字典，里面有dense和sparse两个键，值是列表，里面是向量数据
        search_item_name_list = []

        for idx, item_name in enumerate(item_names):
            dense_data = embeddings.get("dense")[idx]
            sparse_data = embeddings.get("sparse")[idx]
            pass

            # 混合检索
            reqs = get_search_reqs(
                dense_data=[dense_data],
                sparse_data=[sparse_data],
                dense_anns_field="dense_vector",
                sparse_anns_field="sparse_vector"
            )
            # 返回的是一个[],里面是检索结果,两个元素都是AnnSearchRequest实例对象

            res = hybrid_search(
                collection_name=MilvusConfig.item_name_collection,
                reqs=reqs,
                ranker=(0.8, 0.2),
                output_fields=["item_name", "file_title"]
            )
            # print(res,type(res))
            # res的结果是一个列表，列表里的第一个元素也是列表，里面是大模型返回的第一个词的检索结果，每个检索出的结果都是一个字典
            # 字典中有"id","distance","entity",其中entity是检索出来的结果，里面有item_name和file_title两个键
            # print(json_format(res))

            if not res:  # 没有检索请求，就直接跳过
                continue

            for search_item_name_dict in res[0]:
                search_item_name_list.append({
                    "original_item_name": item_name,
                    "search_item_name": search_item_name_dict.get("entity", {}).get("item_name"),
                    # 因为entity是检索出来的结果，因此search_item_name是检索出来的商品名称，也就是导入节点我们存入Milvus的商品名称
                    "score": search_item_name_dict.get("distance", 0)
                    # 这里的score是检索出来的相似度分数，因为中间经过了weighted_ranker进行归一化成了score分数
                })
                # 最终得到的search_item_name_list是一个列表，里面是字典，每个字典里面有三个键值对，
                # 分别是原始的商品名称、检索出来的商品名称和分数
        return search_item_name_list

    def get_item_names(self, history_str: str, original_query: str) -> tuple[list[Any], Any]:
        llm = get_item_llm_model()
        messages = [
            {"role": "system", "content": ITEM_NAME_EXTRACT_SYSTEM_PROMPT},
            {"role": "user",
             "content": ITEM_NAME_EXTRACT_TEMPLATE.format(history_text=history_str, original_query=original_query)}
        ]

        res = llm.invoke(input=messages)
        # print(res,type(res))  # 返回的是一个Response对象，里面有content属性，里面才是我们想要的json字符串
        res_json = res.content
        # print(res_json, type(res_json)) # 返回的是一个json字符串
        res_data = json.loads(res_json)  # 返回的是一个json字符串，需要反序列化为python的字典对象
        # print(res_data,type(res_data)) # 字典

        item_names = res_data.get("item_names", [])  # 字典内部是键值对，其中item_names是键，它的值是一个列表，里面是大模型识别的商品名字
        item_names = [item.replace("\n", "").replace("\t", "").replace(" ", "") for item in item_names]
        # 模型返回的结果可能有空格，为防止检索时解析错误，将空格统一去除
        rewritten_query = res_data.get("rewritten_query", original_query)
        return item_names, rewritten_query

    def get_history_str(self, state: QueryGraphState) -> tuple[str, str, str, Any | None]:
        original_query = state.get("original_query")
        session_id = state.get("session_id")
        if not original_query:
            logger.error("原始问题不能为空")
            raise ValueError("原始问题不能为空")

        if not session_id:
            logger.error("会话ID不能为空")
            raise ValueError("会话ID不能为空")

        history_list = get_recent_messages(session_id)
        # 把当前这个用户的问题 立即保存历史记录
        message_id = save_chat_messages(
            session_id=session_id,
            role="user",
            text=original_query)

        # 把历史记录中的role和text拼接起来，形成一个字符串，然后和原始问题一起交给大模型
        history_str = ''
        for history in history_list:
            role = history.get('role')
            text = history.get('text')
            history_str += f"{role}: {text}\n"
        return history_str, message_id, original_query, session_id


if __name__ == '__main__':

    #模拟会话历史
    # session_id = "test_001"
    # save_chat_messages(session_id, "user", "咨询下烫金机。")
    # save_chat_messages(session_id, "assistant", "您好。请问是哪个型号")
    # save_chat_messages(session_id, "user", "hak180")
    # save_chat_messages(session_id, "assistant", "具体有什么问题呢？")
    create_queue("test_task")
    # 初始化图状态
    init_state = {
        "task_id": "test_task",
        "session_id": "test_001",
        "original_query": "咋用？"
    }

    # 创建节点对象
    node_item_name_confirm = NodeItemNameConfirm()
    # 执行节点的单元测试
    result = node_item_name_confirm(init_state)
    # 将返回的图状态进行json序列化
    logger.info(json_format(result))