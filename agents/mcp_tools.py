"""MCP Client 适配器 + 工具定义（Pydantic schemas + 工具列表）。

工具通过 stdio 连接本地 mcp_server.py，实现能力隔离与最小权限。
"""
import asyncio
import json
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from pydantic import BaseModel, Field
from langchain_core.tools import StructuredTool


# =============================================================================
# 🔌 MCP CLIENT ADAPTER
# =============================================================================

async def call_mcp_tool(tool_name, arguments):
    """连接 mcp_server.py，调用指定工具并返回结果文本。"""
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except Exception:
            pass

    server_params = StdioServerParameters(command=sys.executable, args=["mcp_server.py"])

    try:
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments)
                if result.content:
                    return result.content[0].text
                return "Tool executed."
    except Exception as e:
        return f"Error: {e}"


def create_mcp_tool(name, description, args_schema):
    """用 StructuredTool 包装 MCP 工具，强制 Pydantic 校验参数。"""
    def wrapped_tool(**kwargs):
        return asyncio.run(call_mcp_tool(name, kwargs))
    return StructuredTool.from_function(
        func=wrapped_tool, name=name, description=description, args_schema=args_schema
    )


# =============================================================================
# 🛠️ TOOL DEFINITIONS & SPLIT
# =============================================================================

class FetchApiSpecInput(BaseModel):
    source: str = Field(..., description="Swagger/OpenAPI URL 或本地文件路径")


class GetTestFailureInput(BaseModel):
    log_content: str = Field("", description="pytest 日志文本")
    log_file: str = Field("", description="pytest 日志文件路径")


class UpdateTestScriptInput(BaseModel):
    script_path: str = Field(..., description="测试脚本路径")
    anchor: str = Field(..., description="待替换的旧代码片段")
    new_code: str = Field(..., description="新代码内容")


class RunPytestCodeInput(BaseModel):
    code: str = Field(..., description="pytest 测试代码字符串（来自 state.test_code）")
    timeout: int = Field(60, description="超时秒数")


class GenerateTestReportInput(BaseModel):
    execution_result: str = Field(..., description="run_pytest_code 返回的 JSON 结果")
    test_code: str = Field("", description="测试代码（可选，用于报告展示）")
    retry_count: int = Field(0, description="当前重试次数")


# Worker 1 Tools: 用例生成&诊断修复 (Diagnosis & Repair)
diag_repair_tools = [
    create_mcp_tool("fetch_api_spec", "获取 Swagger/OpenAPI 接口契约", FetchApiSpecInput),
    create_mcp_tool("get_test_failure_detail", "解析 pytest 失败日志", GetTestFailureInput),
    create_mcp_tool("update_test_script", "修改测试脚本代码片段", UpdateTestScriptInput),
]

# Worker 2 Tools: 沙箱执行&结果采集 (Sandbox Execution)
sandbox_exec_tools = [
    create_mcp_tool("run_pytest_code", "沙箱执行 pytest 代码字符串", RunPytestCodeInput),
    create_mcp_tool("generate_test_report", "生成 markdown 测试报告", GenerateTestReportInput),
]
