"""共享状态定义与代码清洗工具。"""
import re
from typing import Annotated, List, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    """测开自愈流程核心状态字段。"""
    messages: Annotated[List[BaseMessage], add_messages]  # 对话历史（复用原有消息累加逻辑）
    next: str                                             # Supervisor 路由目标
    requirement: str                                      # 接口需求/Swagger文档地址/OpenAPI JSON内容
    test_code: str                                        # LLM生成的pytest自动化代码
    execution_result: str                                 # 沙箱执行后的日志、报错堆栈
    retry_count: int                                      # 代码修复重试计数器（上限3次）


def _extract_python_code(text: str) -> str:
    """代码清洗：提取 ```python 代码块，剔除多余解释文本。"""
    matches = re.findall(r"```python\s*\n(.*?)```", text, re.DOTALL)
    if matches:
        return "\n\n".join(matches)
    return text
