"""SandboxExecWorker：沙箱执行 & 结果采集节点。

直接本地执行 pytest（绕过 MCP 和 LLM，避免子进程卡死），
若 test_code 为空则走 LLM 兜底流程。
"""
import json
import os
import sys as _sys
import subprocess as _sp

from langchain_core.messages import SystemMessage, AIMessage
from langchain_ollama import ChatOllama

from agents.state import AgentState
from agents.mcp_tools import sandbox_exec_tools


def sandbox_exec_node(state: AgentState):
    """Worker2：沙箱执行&结果采集节点。直接本地执行 pytest，不走 MCP，确保快速可靠。"""
    test_code = state.get("test_code", "") or ""

    # 直接本地执行 pytest（绕过 MCP 和 LLM，避免子进程卡死）
    if test_code:
        # agents/sandbox_exec.py -> 项目根目录
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        test_dir = os.path.join(project_root, "tests")
        test_file = os.path.join(test_dir, "test_generated.py")
        os.makedirs(test_dir, exist_ok=True)
        with open(test_file, "w", encoding="utf-8") as f:
            f.write(test_code)
        # 精简 env，移除代理变量
        keep = ("PATH", "PYTHONPATH", "SYSTEMROOT", "SYSTEMDRIVE", "TEMP", "TMP", "USERPROFILE", "HOME")
        env = {k: v for k, v in os.environ.items() if k.upper() in keep}
        for pk in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
            env.pop(pk, None)
        proc = None
        try:
            proc = _sp.Popen(
                [_sys.executable, "-m", "pytest", test_file, "-v", "--tb=short", "--no-header"],
                stdout=_sp.PIPE, stderr=_sp.PIPE, text=True, env=env,
                cwd=project_root,
                creationflags=_sp.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
            )
            stdout, stderr = proc.communicate(timeout=30)
            execution_result = json.dumps({
                "exit_code": proc.returncode,
                "passed": proc.returncode == 0,
                "test_file": test_file,
                "stdout": stdout[-5000:],
                "stderr": stderr[-5000:]
            }, ensure_ascii=False, indent=2)
        except _sp.TimeoutExpired:
            import signal
            try:
                if os.name == "nt":
                    proc.send_signal(signal.CTRL_BREAK_EVENT)
                else:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except Exception:
                proc.kill()
            proc.wait(timeout=5)
            execution_result = json.dumps({"exit_code": -1, "passed": False, "error": "timeout after 30s", "test_file": test_file}, ensure_ascii=False)
        except Exception as e:
            execution_result = json.dumps({"exit_code": -1, "passed": False, "error": str(e), "test_file": test_file}, ensure_ascii=False)
        result_msg = AIMessage(content=f"已执行测试代码。结果：{execution_result[:500]}")
        return {"messages": [result_msg], "execution_result": execution_result}

    # 如果没有 test_code，走 LLM 流程（兜底）
    system_prompt = (
        "你是沙箱执行专家。请调用 run_pytest_code 执行测试代码。拿到结果后直接总结，不要调其他工具。"
    )
    messages = [SystemMessage(content=system_prompt)] + state["messages"]
    if test_code:
        messages.append(SystemMessage(
            content=f"【待执行测试代码】\n```python\n{test_code}\n```\n请调用 run_pytest_code 执行上述代码。"
        ))
    llm = ChatOllama(model="llama3.1", temperature=0)
    llm_with_tools = llm.bind_tools(sandbox_exec_tools)
    result = llm_with_tools.invoke(messages)
    # 提取执行结果
    execution_result = ""
    last_tool_content = ""
    for msg in reversed(state["messages"]):
        if hasattr(msg, "tool_call_id") and msg.tool_call_id:
            msg_content = msg.content if isinstance(msg.content, str) else str(msg.content)
            if not last_tool_content:
                last_tool_content = msg_content
            if "passed" in msg_content and "exit_code" in msg_content:
                execution_result = msg_content
                break
    if not execution_result and last_tool_content:
        execution_result = last_tool_content
    updates = {"messages": [result]}
    if execution_result:
        updates["execution_result"] = execution_result
    return updates
