# CLAUDE.md

本文件为 Claude Code (claude.ai/code) 在本仓库工作时提供指引。

## 项目概述

基于 LangGraph 多智能体的接口测试自愈 Agent。本地推理（Ollama + llama3.1），实现"契约拉取 → pytest 用例生成 → 沙箱执行 → 失败日志诊断 → 自动修复 → 重试 → 报告"闭环。

## 架构

单进程 LangGraph 工作图 + MCP 进程隔离工具服务器。

- `final_agent.py` — 主入口，被 `streamlit run` 加载
- `ui.py` — Streamlit UI（`st.set_page_config` 必须是第一个 streamlit 命令，故由 final_agent.py 顶部 `from ui import render_ui` 触发）
- `agents/` — 多智能体节点模块包
  - `state.py` — `AgentState` TypedDict + `_extract_python_code` 代码清洗
  - `mcp_tools.py` — MCP Client 适配器 + 5 个 Pydantic schemas + `diag_repair_tools` / `sandbox_exec_tools` 两组工具列表
  - `diag_repair.py` — `diag_repair_node`（Worker1：测试代码生成 & 诊断修复）
  - `sandbox_exec.py` — `sandbox_exec_node`（Worker2：沙箱执行 & 结果采集，本地直接跑 pytest 绕过 MCP）
  - `supervisor.py` — `supervisor_node` + `self_heal_check` + `finish_node` + `_persist_self_heal_round`
  - `graph.py` — `build_app()` 构建并编译 LangGraph 工作图（带 SQLite checkpoint）
- `mcp_server.py` — FastMCP 工具服务器，5 个工具：`fetch_api_spec` / `get_test_failure_detail` / `update_test_script` / `run_pytest_code` / `generate_test_report`
- `mock_server.py` — Flask Mock 后端 + 5 个用户接口 + Swagger UI 静态服务（演示用）
- `swagger_openapi/openapi.yaml` — OpenAPI 接口契约
- `multi_agent_memory.sqlite` — LangGraph checkpoint + 业务历史表（`self_heal_rounds` / `test_history`）

依赖链无循环：`multi_agent → ui + agents.graph → {state, mcp_tools, diag_repair, sandbox_exec, supervisor}`

## 运行

**前置：** Python 3.12+，Ollama 运行（`ollama serve`），llama3.1 已拉取（`ollama pull llama3.1`）。

```bash
uv venv
.venv\Scripts\activate  # Windows
uv pip install -e .

# 可选：启动 Mock 后端
python mock_server.py

# 启动 Agent
streamlit run final_agent.py
```

无配置测试套件或 linter。

## 关键设计模式

- **Supervisor 路由**：LLM-based Supervisor 决定 Worker 分发，输出后处理强制映射到合法节点名，兜底防 LLM 乱输出
- **ReAct 循环**：Worker 通过 LangGraph 条件边和 `_should_continue` 实现 reason→tool→result 循环
- **MCP 协议**：工具隔离在独立 FastMCP 进程，Agent 以 MCP Client 身份经 stdio 调用
- **SQLite checkpointing**：对话状态跨工具调用持久化（`multi_agent_memory.sqlite`）
- **硬编码自愈判断**：`self_heal_check` 用 `if` 而非 LLM 判断重试/终止，确保可终止性

## 安全护栏（修改工具时必须保留）

- **沙箱执行隔离**：`run_pytest_code` 用 subprocess + 进程组 + env 白名单（仅 PATH/PYTHONPATH/SYSTEMROOT 等）+ 移除代理变量 + 超时强杀
- **路径穿越防护**：`_validate_path` 拒绝 `..`、绝对路径、非 http 协议的冒号路径
- **工具调用防死循环**：`_should_continue` 统计最近 12 条消息 tool_calls，>=4 强制回 Supervisor
- **角色分离**：`diag_repair_tools` 与 `sandbox_exec_tools` 物理隔离，Worker 各自只能 bind 自己的工具组

## 路径注意事项

- `agents/sandbox_exec.py` 在子目录，用 `os.path.dirname(os.path.dirname(os.path.abspath(__file__)))` 回溯到项目根定位 `tests/` 和 pytest 的 `cwd`
- `agents/mcp_tools.py` 的 `StdioServerParameters(args=["mcp_server.py"])` 依赖运行时 cwd（streamlit 在项目根启动），若移动文件需同步更新
- SQLite 文件路径（`multi_agent_memory.sqlite`）是相对路径，依赖 cwd

## 可选：LangSmith 可观测性

```bash
set LANGCHAIN_TRACING_V2=true
set LANGCHAIN_API_KEY=your-api-key
```

默认在 tracing 的 default 项目下查看，可自行建项目并加上 `set LANGCHAIN_PROJECT=你的项目名`。

## Skills

skill 文件夹仅为结构需要，可自行添加配置。
