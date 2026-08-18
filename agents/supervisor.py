"""Supervisor + 自愈判断 + 终止节点 + SQLite 持久化。

- supervisor_node: LLM 路由（生成→执行），仅负责"该去哪个 Worker"
- self_heal_check: 硬编码自愈条件边（不走 LLM，确保可终止性）
- finish_node: 生成最终报告 + 写入 test_history 表
- _persist_self_heal_round: 每轮自愈快照持久化
"""
import json
import re
import sqlite3
import datetime

from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langchain_ollama import ChatOllama

from agents.state import AgentState


# 每轮自愈过程持久化（写入 self_heal_rounds 业务表）
def _persist_self_heal_round(state: AgentState, round_type: str):
    """将当前轮次的 requirement / test_code / execution_result / retry_count 写入 self_heal_rounds 表。
    round_type 取值：
      - "exec_result"：SandboxExecWorker 执行完成后记录本轮执行结果
      - "retry"      ：self_heal_check 触发自愈时记录修复前快照
      - "finish"     ：finish_node 终止时记录最终状态
    """
    try:
        requirement = state.get("requirement", "") or ""
        test_code = state.get("test_code", "") or ""
        execution_result = state.get("execution_result", "") or ""
        retry_count = state.get("retry_count", 0) or 0

        # 解析执行结果摘要
        passed = False
        stdout = ""
        stderr = ""
        error = ""
        try:
            r = json.loads(execution_result) if execution_result else {}
            passed = r.get("passed", False)
            stdout = r.get("stdout", "")
            stderr = r.get("stderr", "")
            error = r.get("error", "")
        except Exception:
            stderr = execution_result

        conn = sqlite3.connect("multi_agent_memory.sqlite", check_same_thread=False)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS self_heal_rounds (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT,
                round_type TEXT,
                requirement TEXT,
                test_code TEXT,
                execution_result TEXT,
                passed INTEGER,
                retry_count INTEGER,
                stdout TEXT,
                stderr TEXT,
                error TEXT
            )
        """)
        conn.execute("""
            INSERT INTO self_heal_rounds
            (created_at, round_type, requirement, test_code, execution_result, passed, retry_count, stdout, stderr, error)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            round_type,
            requirement[:5000],
            test_code[:5000],
            execution_result[:5000],
            int(passed),
            retry_count,
            stdout[:5000],
            stderr[:5000],
            error[:2000]
        ))
        conn.commit()
        conn.close()
    except Exception:
        # 持久化失败不阻塞主流程
        pass


def supervisor_node(state: AgentState):
    """LLM Supervisor：依据强约束提示词分发任务。
    - 仅负责"该去哪个 Worker"的前向路由（生成→执行）；
    - 执行后的自愈循环判断由 self_heal_check 硬编码节点处理，不走本节点。
    """
    # （1）重写系统提示词：固定业务流程顺序，禁止乱跳
    system_prompt = (
        "你是调度主管（Supervisor）。当前系统只有以下 2 个 Worker，无其它工具：\n"
        "1. DiagRepairWorker（Worker1）：读取接口文档、分析报错、自动修复测试脚本；\n"
        "2. SandboxExecWorker（Worker2）：执行 pytest 代码，收集运行结果。\n\n"
        "【调度规则，固定顺序，禁止违反】\n"
        "- 初始任务：固定派给 DiagRepairWorker 生成代码；\n"
        "- DiagRepairWorker 产出代码后：固定分发到 SandboxExecWorker 执行；\n"
        "- 执行失败后：再次分配给 DiagRepairWorker 做自愈修复；\n"
        "- 禁止跳过步骤、禁止调换顺序、禁止调用已删除的文件/计算工具。\n\n"
        "【输出格式】\n"
        "你只能输出唯一节点名称：DiagRepairWorker 或 SandboxExecWorker 或 END。\n"
        "禁止输出任何解释性文字、禁止输出大段自然语言、禁止输出 JSON。\n"
        "流程必须遵循 生成→执行→（失败则）修复 循环，不得调换顺序。"
    )

    # （2）限定 LLM 输出格式：构造状态摘要 + 强制输出节点名
    test_code = state.get("test_code", "") or ""
    execution_result = state.get("execution_result", "") or ""
    state_brief = (
        f"当前状态：test_code={'有' if test_code else '无'}，"
        f"execution_result={'有' if execution_result else '无'}。\n"
        f"下一个节点是？只输出节点名称（DiagRepairWorker / SandboxExecWorker / END）。"
    )

    llm = ChatOllama(model="llama3.1", temperature=0)
    messages = [SystemMessage(content=system_prompt)] + state["messages"]
    messages.append(HumanMessage(content=state_brief))

    response = llm.invoke(messages)
    content = (response.content if isinstance(response.content, str) else str(response.content)).strip()

    # 后处理：强制映射到合法节点，兜底防 LLM 乱输出
    content_lower = content.lower()
    if "diagrepair" in content_lower or "code_generator" in content_lower:
        next_step = "DiagRepairWorker"
    elif "sandbox" in content_lower or "test_executor" in content_lower:
        next_step = "SandboxExecWorker"
    elif "end" in content_lower or "finish" in content_lower:
        next_step = "FINISH"
    else:
        # 兜底：按硬规则推断
        # 有 test_code 就路由到 SandboxExecWorker（执行/重新执行）
        # 无 test_code 路由到 DiagRepairWorker（初始生成）
        # execution_result 不参与 Supervisor 路由判断（自愈循环由 self_heal_check 硬编码处理）
        if not test_code:
            next_step = "DiagRepairWorker"
        else:
            next_step = "SandboxExecWorker"

    return {"next": next_step, "messages": [response]}


def self_heal_check(state: AgentState):
    """硬编码自愈判断节点：读取 retry_count、execution_result 做 if 判断。
    - passed == True → FINISH（输出报告）
    - passed == False && retry_count < 3 → retry_count+1，回 DiagRepairWorker
    - retry_count >= 3 → FINISH（汇总失败日志）
    """
    execution_result = state.get("execution_result", "") or ""
    retry_count = state.get("retry_count", 0) or 0

    try:
        result = json.loads(execution_result) if execution_result else {}
        passed = result.get("passed", False)
    except Exception:
        passed = False

    # 记录本轮执行结果（自愈判断前的快照）
    _persist_self_heal_round(state, "exec_result")

    updates = {"retry_count": retry_count}
    if passed:
        updates["next"] = "FINISH"
    elif not execution_result:
        # execution_result 为空：LLM 未调用 run_pytest_code，无法自愈，直接终止
        updates["next"] = "FINISH"
    elif retry_count < 3:
        # 记录自愈触发（修复前快照）
        _persist_self_heal_round(state, "retry")
        # 自愈循环：retry_count+1
        # 不清空 execution_result —— DiagRepairWorker 需要读取报错信息进行修复
        # Supervisor 路由由兜底逻辑保证：有 test_code 即路由到 SandboxExecWorker
        updates["retry_count"] = retry_count + 1
        updates["next"] = "RETRY"
    else:
        updates["next"] = "FINISH"
    return updates


def finish_node(state: AgentState):
    """生成最终测试报告并保存到 SQLite 业务历史表。
    - 读取 execution_result、test_code、retry_count；
    - 调用 generate_test_report 工具逻辑生成 markdown 报告；
    - 写入 SQLite 业务表 test_history。
    """
    execution_result = state.get("execution_result", "") or ""
    test_code = state.get("test_code", "") or ""
    retry_count = state.get("retry_count", 0) or 0

    # 记录最终轮次（终止状态）
    _persist_self_heal_round(state, "finish")

    # 解析执行结果：execution_result 可能是 JSON 字符串，也可能嵌套在 messages 的 ToolMessage 中
    passed = False
    exit_code = "N/A"
    stdout = ""
    stderr = ""
    error = ""

    # 策略1：优先从 state.execution_result 解析
    if execution_result:
        try:
            result = json.loads(execution_result)
            if isinstance(result, dict):
                passed = result.get("passed", False)
                exit_code = result.get("exit_code", "N/A")
                stdout = result.get("stdout", "")
                stderr = result.get("stderr", "")
                error = result.get("error", "")
        except Exception:
            stderr = execution_result

    # 策略2：如果 stdout 仍为空，从 messages 里找 run_pytest_code 的 ToolMessage
    if not stdout:
        for msg in reversed(state.get("messages", [])):
            if hasattr(msg, "tool_call_id") and msg.tool_call_id:
                msg_content = msg.content if isinstance(msg.content, str) else str(msg.content)
                try:
                    r = json.loads(msg_content)
                    if isinstance(r, dict) and "exit_code" in r:
                        passed = r.get("passed", False)
                        exit_code = r.get("exit_code", "N/A")
                        stdout = r.get("stdout", "")
                        stderr = r.get("stderr", "")
                        error = r.get("error", "")
                        break
                except Exception:
                    continue

    # 统计用例：从 pytest summary 行提取（避免 -v 输出中 FAILED 出现2次导致重复计数）
    m_passed = re.search(r"(\d+)\s+passed", stdout)
    m_failed = re.search(r"(\d+)\s+failed", stdout)
    passed_cases = int(m_passed.group(1)) if m_passed else 0
    failed_cases = int(m_failed.group(1)) if m_failed else 0
    total = passed_cases + failed_cases
    pass_rate = f"{(passed_cases / total * 100):.1f}%" if total > 0 else "N/A"
    status = "✅ 全部通过" if passed else ("❌ 重试耗尽" if retry_count >= 3 else "❌ 存在失败")

    # 生成 markdown 报告
    report_lines = [
        f"# 测试执行最终报告",
        f"",
        f"## 执行状态",
        f"- 状态：{status}",
        f"- 退出码：{exit_code}",
        f"- 重试次数：{retry_count} / 3",
        f"- 用例总数：{total}",
        f"- 通过：{passed_cases}",
        f"- 失败：{failed_cases}",
        f"- 通过率：{pass_rate}",
    ]
    if error:
        report_lines.append(f"- 错误：{error}")
    if failed_cases > 0 and stdout:
        report_lines.append(f"\n## 失败用例摘要")
        for line in stdout.splitlines():
            if "FAILED" in line:
                report_lines.append(f"- {line.strip()}")
    if stderr:
        report_lines.append(f"\n## stderr 摘要")
        report_lines.append(f"```\n{stderr[-2000:]}\n```")
    if test_code:
        report_lines.append(f"\n## 测试代码")
        report_lines.append(f"```python\n{test_code[:3000]}\n```")
    report_lines.append(f"\n---\n*报告生成时间：{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")
    report = "\n".join(report_lines)

    # 保存 SQLite 业务历史记录
    try:
        hist_conn = sqlite3.connect("multi_agent_memory.sqlite", check_same_thread=False)
        hist_conn.execute("""
            CREATE TABLE IF NOT EXISTS test_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT,
                status TEXT,
                passed INTEGER,
                retry_count INTEGER,
                total_cases INTEGER,
                passed_cases INTEGER,
                failed_cases INTEGER,
                pass_rate TEXT,
                execution_result TEXT,
                test_code TEXT,
                report TEXT
            )
        """)
        hist_conn.execute("""
            INSERT INTO test_history
            (created_at, status, passed, retry_count, total_cases, passed_cases, failed_cases, pass_rate, execution_result, test_code, report)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            status, int(passed), retry_count, total, passed_cases, failed_cases, pass_rate,
            execution_result, test_code, report
        ))
        hist_conn.commit()
        hist_conn.close()
    except Exception as e:
        report += f"\n\n⚠️ SQLite 历史保存失败：{e}"

    return {"messages": [AIMessage(content=report)]}
