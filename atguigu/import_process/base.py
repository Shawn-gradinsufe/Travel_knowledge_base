from abc import ABC, abstractmethod
import time
from atguigu.import_process.state import ImportGraphState
from atguigu.tool.logger import logger
from atguigu.tool.task_utils import add_running_task, add_done_task, add_node_duration


class NodeBase(ABC):
    name = "node_base"
    def __init__(self):
        if self.name == "node_base":
            logger.error(f"节点的{self.__class__.__name__}未配置，为节点名称")
            raise Exception(f"节点的{self.__class__.__name__}未配置，为节点名称")

    def __call__(self,state: ImportGraphState):
        try:
            start_time = time.time()
            task_id = state.get("task_id")
            # 修改节点状态为开始运行
            add_running_task(task_id,self.name)

            logger.info(f"节点{self.name}开始执行")
            result = self.process(state)
            logger.info(f"节点{self.name}执行完毕")

            # 修改节点状态为执行完成
            add_done_task(task_id,self.name)
            end_time = time.time()

            # 记录节点耗时
            add_node_duration(task_id,self.name,end_time-start_time)

            return result
        except Exception as e:
            logger.error(e)
            raise e

    @abstractmethod
    def process(self,state: ImportGraphState):
        pass