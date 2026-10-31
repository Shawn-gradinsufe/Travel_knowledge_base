from typing import List
from pymilvus.model.hybrid import BGEM3EmbeddingFunction

from atguigu.config.config import BGEM3Config
from atguigu.tool.json_format import json_format

bgem3_model = None
def get_bgem3_model():
    global bgem3_model
    if not bgem3_model:
        # 优先用本地模型目录，避免联网下载：model_name 传 "BAAI/bge-m3" 会被当成 Hub repo id，
        # 从而去 HF_ENDPOINT（hf-mirror.com）拉 tokenizer_config.json，网络不通时直接超时。
        model_path = BGEM3Config.bge_m3_path or BGEM3Config.bge_m3
        bgem3_model=BGEM3EmbeddingFunction(
            model_name=model_path,
            device=BGEM3Config.bge_device,
            use_fp16=BGEM3Config.bge_fp16,
        )
    return bgem3_model

def get_bge_embedding(text:List[str]):
    model = get_bgem3_model()
    result = model.encode_documents(text)

    return {
        "dense":[item.tolist() for item in result.get("dense")],
        "sparse":[dict(zip(item.indices.tolist(),item.data.tolist())) for item in result.get("sparse")]
    }

if __name__ == '__main__':
    result = get_bge_embedding(["我爱杨幂","我爱赵丽颖"])
    print(json_format(result))