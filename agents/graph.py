"""构建并编译 LangGraph 工作图。

节点拓扑：
  START -> Supervisor
  Supervisor --(DiagRepairWorker|SandboxExecWorker|FINISH)--> 对应节点
  DiagRepairWorker --(continue->DiagRepair_Tools | back_to_manager->Supervisor)
  SandboxExecWorker --(continue->SandboxExec_Tools | back_to_manager->self_heal_check)
  DiagRepair_Tools -> DiagRepairWorker
  SandboxExec_Tools -> SandboxExecWorker
  self_heal_check --(RETRY->DiagRepairWorker | FINISH->finish_node)
  finish_node -> END
"""
import sqlite3

from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.sqlite import SqliteSaver

from agents.state import AgentState
from agents.mcp_tools import diag_repair_tools, sandbox_exec_tools
from agents.diag_repair import diag_repair_node
from agents.sandbox_exec import sandbox_exec_node
from agents.supervisor import supervisor_node, self_heal_check, finish_node


def _should_continue(state: AgentState):
    """ReAct 条件边：有 tool_calls 则继续调工具，否则回 Supervisor。
    防 ReAct 死循环：统计最近消息中带 tool_calls 的 AIMessage 数量，>=4 强制回 Supervisor。
    """
    last_msg = state["messages"][-1]
    if last_msg.tool_calls:
        recent_tool_calls = sum(
            1 for m in state["messages"][-12:]
            if hasattr(m, 'tool_calls') and m.tool_calls
        )
        if recent_tool_calls >= 4:
            return "back_to_manager"
        return "continue"
    return "back_to_manager"


def build_app():
    """构建并编译 LangGraph 工作图，返回带 SQLite checkpoint 的 compiled app。"""
    workflow = StateGraph(AgentState)

    # Add Nodes
    workflow.add_node("Supervisor", supervisor_node)
    workflow.add_node("DiagRepairWorker", diag_repair_node)
    workflow.add_node("SandboxExecWorker", sandbox_exec_node)
    workflow.add_node("DiagRepair_Tools", ToolNode(diag_repair_tools))
    workflow.add_node("SandboxExec_Tools", ToolNode(sandbox_exec_tools))
    workflow.add_node("self_heal_check", self_heal_check)
    workflow.add_node("finish_node", finish_node)

    # Entry Point
    workflow.add_edge(START, "Supervisor")

    # Supervisor Conditional Logic（LLM 路由：生成→执行）
    workflow.add_conditional_edges(
        "Supervisor",
        lambda x: x["next"],
        {
            "DiagRepairWorker": "DiagRepairWorker",
            "SandboxExecWorker": "SandboxExecWorker",
            "FINISH": "finish_node"
        }
    )

    # Worker -> Tool Logic（ReAct）
    workflow.add_conditional_edges(
        "DiagRepairWorker", _should_continue,
        {"continue": "DiagRepair_Tools", "back_to_manager": "Supervisor"}
    )
    workflow.add_conditional_edges(
        "SandboxExecWorker", _should_continue,
        {"continue": "SandboxExec_Tools", "back_to_manager": "self_heal_check"}
    )

    # Tool -> Back to Worker (Standard ReAct pattern)
    workflow.add_edge("DiagRepair_Tools", "DiagRepairWorker")
    workflow.add_edge("SandboxExec_Tools", "SandboxExecWorker")

    # self_heal_check Conditional Logic（硬编码：重试 or 结束）
    workflow.add_conditional_edges(
        "self_heal_check",
        lambda x: x["next"],
        {
            "RETRY": "DiagRepairWorker",
            "FINISH": "finish_node"
        }
    )

    # 终止节点 → END
    workflow.add_edge("finish_node", END)

    # Compile with SQLite memory
    conn = sqlite3.connect("multi_agent_memory.sqlite", check_same_thread=False)
    memory = SqliteSaver(conn)
    return workflow.compile(checkpointer=memory)
