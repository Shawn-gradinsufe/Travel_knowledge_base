# 专门给mongodb的操作做封装，后期操作mongo的增删改查全部对应这个文件中的一个函数
# 1、获取单例的mongo链接对象
import time
from pymongo import MongoClient

from atguigu.config.config import MongoConfig

mongo_client=None
def get_mongo_client():
    global mongo_client
    if not mongo_client:
        mongo_client = MongoClient(
            host=MongoConfig.mongo_host, # 主机
            port=MongoConfig.mongo_port, # 端口
        )
        # print(mongo_client)
    return mongo_client


# db = mongo_client['mydatabase']


mongo_tool = None
def get_mongo_tool():
    global mongo_tool
    if mongo_tool is None:
        mongo_client=get_mongo_client() # 获取链接对象，目的是为了创建数据库
        db = mongo_client[MongoConfig.mongo_db_name] # 创建数据获取数据库对象
        mongo_tool = db["chat_message"] # 创建集合对象 获取集合对象
        mongo_tool.create_index([("session_id",1),("ts",-1)])  # 创建联合索引

    return mongo_tool




# 表的增删改查
# clear_history清空某个session_id的所有信息
def clear_history(session_id):
    mongo_tool = get_mongo_tool()
    mongo_tool.delete_many({"session_id":session_id})


# get_recent_messages 根据session_id获取最近的n条消息（按时间正序返回）
def get_recent_messages(session_id,n=10):
    mongo_tool = get_mongo_tool()
    # 先按时间倒序取最近 n 条
    result = mongo_tool.find({"session_id":session_id}).sort("ts",-1).limit(n)
    rows = list(result)
    # 再翻转成正序：拼历史对话时，大模型需要的是"从旧到新"，
    # 原来的实现直接返回倒序，喂给模型的上下文是反的。
    rows.reverse()
    return rows


# 增改一体，一个函数可以增也可以改，增和改在这里都是全量
# save_chat_messages保存历史记录（根据id决定是添加还是修改）
# 一条数据如果是新增，那么它还没进入到数据库，此时不可能有id
# 一条数据如果是修改，那么代表这条数据是从数据库中来的，那么一定有id
def save_chat_messages(session_id,role,text,rewritten_query=None,item_names=None,ts=None,message_id=None):
    mongo_tool = get_mongo_tool()
    if message_id: # 如果有message_id，那么就是修改
        # 修改
        mongo_tool.update_one({ "_id": message_id },{
            "$set": {
                "session_id": session_id,
                "role": role,
                "text": text,
                "rewritten_query": rewritten_query,
                "item_names": item_names,
                "ts": ts or time.time(),
            }
        })
    else: # 没有message_id，那么就是新增
        # 新增
        result = mongo_tool.insert_one({
            "session_id": session_id,
            "role": role,
            "text": text,
            "rewritten_query": rewritten_query,
            "item_names": item_names,
            "ts": ts or time.time(),
        })

        return result.inserted_id # 添加成功返回新增的数据id,注意打印的时候看不出来,要返回就得返回inserted_id,而且是一个ObjectId类型

def update_history_item_names(ids,item_names,rewritten_query):
    mongo_tool = get_mongo_tool()
    mongo_tool.update_many({"_id":{"$in":ids}},{
        "$set":{
            "item_names":item_names,
            "rewritten_query":rewritten_query,
        }
    })


def update_message_meta(message_id, item_names=None, rewritten_query=None):
    """
    只更新指定的一条消息。

    原来的 update_history_item_names 会把最近 N 条历史**全部**覆写成当前轮次的
    item_names / rewritten_query，导致历史记录被污染（翻旧对话时看到的全是新问题的改写）。
    这里按 _id 精确更新，只动刚写入的那条用户消息。
    """
    if not message_id:
        return
    mongo_tool = get_mongo_tool()
    payload = {}
    if item_names is not None:
        payload["item_names"] = item_names
    if rewritten_query is not None:
        payload["rewritten_query"] = rewritten_query
    if not payload:
        return
    mongo_tool.update_one({"_id": message_id}, {"$set": payload})



if __name__ == "__main__":

    # 模拟会话历史
    session_id = "test_001"
    result = save_chat_messages(session_id, "user", "咨询下烫金机。")
    print(result,type(result))