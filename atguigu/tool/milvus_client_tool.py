from pymilvus import MilvusClient, AnnSearchRequest, WeightedRanker

from atguigu.config.config import MilvusConfig

milvus_client = None

def get_milvus_client():
    global milvus_client
    if not milvus_client:
        milvus_client = MilvusClient(
            uri=MilvusConfig.milvus_url,
            # 没有配置db_name，默认使用的是default数据库，如果实现创建好了数据库，需要配置db_name
        )
    return milvus_client


def get_search_reqs(
    dense_data,# list
    sparse_data,
    dense_anns_field, # str  对应的milvus字段名
    sparse_anns_field, # str 对应的milvus字段名
    limit=10,
    expr=None, # str
    dense_param=None, # dict
    sparse_param=None, # dict
):
    """
        把稠密向量和稀疏向量分别创建自己的检索请求，实例化AnnSearchRequest，拿到实例
        :return: 返回的是两个检索请求的实例组成的列表
    """
    if not dense_param:
        dense_param = {
            "metric_type": "COSINE"
        }
    if not sparse_param:
        sparse_param = {
            "metric_type": "IP"
        }


    dense_req = AnnSearchRequest(
        data=dense_data,
        anns_field=dense_anns_field,
        param=dense_param,
        limit=limit,
        expr=expr
    )

    sparse_req = AnnSearchRequest(
        data=sparse_data,
        anns_field=sparse_anns_field,
        param=sparse_param,
        limit=limit,
        expr=expr
    )

    return [dense_req, sparse_req]

def hybrid_search(
        collection_name, # str
        reqs, # 混合检索请求，列表形式，List[AnnSearchRequest]
        limit=10,
        output_fields=None, # List[str] #
        ranker=(0.5,0.5) # BaseRanker或是Function
):
    weighted_ranker = WeightedRanker(*ranker) # 继承BaseRanker类
    # WeightedRanker()参数中有一个*nums的打包参数，表示应该传入多个数值，因此在这里创建实例时需要传入*ranker解包的多个数值

    milvus_client = get_milvus_client()

    res = milvus_client.hybrid_search(
        collection_name=collection_name,
        reqs=reqs,
        ranker=weighted_ranker,
        limit=limit,
        output_fields=output_fields
    )

    return res


