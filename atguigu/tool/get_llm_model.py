from langchain.chat_models import init_chat_model

from atguigu.config.config import LLMConfig


def get_vl_llm_model():
    llm = init_chat_model(
        model=LLMConfig.vl_model,
        model_provider="openai",
        api_key=LLMConfig.openai_api_key,
        base_url=LLMConfig.openai_api_base,
        temperature=LLMConfig.llm_default_temperature
    )
    return llm

def get_item_llm_model():
    llm = init_chat_model(
        model=LLMConfig.item_model,
        model_provider="openai",
        api_key=LLMConfig.openai_api_key,
        base_url=LLMConfig.openai_api_base,
        temperature=LLMConfig.llm_default_temperature
    )
    return llm

if __name__ == '__main__':
    llm = get_vl_llm_model()
    result = llm.invoke(input="你是谁")
    print(result.content)