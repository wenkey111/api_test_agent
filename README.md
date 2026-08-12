# 基于 LangGraph 多智能体的接口测试自愈 Agent

针对"接口契约变更导致自动化测试脚本批量失效"的工程痛点，构建 LLM 驱动的自愈系统，实现 **契约拉取 → pytest 用例生成 → 沙箱执行 → 失败日志诊断 → 自动修复 → 重试 → 报告** 闭环。

本地推理（Ollama + llama3.1），无需外部 API Key。

---

## 核心架构

```
START
  │
  ▼
Supervisor (LLM 路由)
  │
  ├─→ DiagRepairWorker ──→ MCP Tools (fetch_api_spec / get_test_failure_detail / update_test_script)
  │        ▲                       │
  │        │                       ▼
  │        └──────── 返回 Supervisor
  │
  ├─→ SandboxExecWorker ──→ MCP Tools (run_pytest_code / generate_test_report)
  │        │                       │
  │        ▼                       ▼
  │   self_heal_check ───→ 返回 SandboxExecWorker
  │        │
  │        ├─ RETRY (retry_count < 3) ──→ DiagRepairWorker
  │        └─ FINISH ──→ finish_node ──→ END
  └─→ FINISH
```

### 关键设计点

| 模块 | 文件 | 职责 |
|:---|:---|:---|
| **Supervisor** | `agents/supervisor.py` | LLM 路由（生成→执行），强约束提示词防止乱跳步骤 |
| **DiagRepairWorker** | `agents/diag_repair.py` | Worker1：测试用例生成 & 诊断修复，注入历史报错日志做上下文修复 |
| **SandboxExecWorker** | `agents/sandbox_exec.py` | Worker2：沙箱执行 pytest，收集结果 |
| **self_heal_check** | `agents/supervisor.py` | **硬编码**自愈判断（不走 LLM，确保可终止性）：passed→结束 / 失败&retry<3→重试 / retry≥3→终止 |
| **finish_node** | `agents/supervisor.py` | 生成最终报告 + SQLite 历史持久化 |
| **MCP Server** | `mcp_server.py` | FastMCP 进程隔离的 5 个工具（契约解析/日志诊断/脚本修复/沙箱执行/报告生成） |

### 自愈循环

- 失败时不清空 `execution_result`，DiagRepairWorker 读取报错信息做针对性修复
- 重试上限 3 次，超过即终止并汇总失败日志
- 自愈判断用硬编码 `if` 而非 LLM，规避路由不确定性导致死循环
- 每轮快照写入 `self_heal_rounds` 表，终态写入 `test_history` 表

---

## 安全护栏

| 护栏 | 实现位置 | 说明 |
|:---|:---|:---|
| **沙箱执行隔离** | `mcp_server.py#run_pytest_code` | `subprocess` + 进程组隔离 + 超时强杀 + env 白名单（仅保留 PATH/PYTHONPATH 等）+ 移除代理变量 |
| **路径穿越防护** | `mcp_server.py#_validate_path` | 拦截 `..`、绝对路径、非 http 协议的冒号路径 |
| **工具调用防死循环** | `agents/graph.py#_should_continue` | 统计最近 12 条消息中 tool_calls 数量，>=4 强制回 Supervisor |
| **角色分离** | `agents/mcp_tools.py` | DiagRepairWorker 只能访问 fetch/failure/update 工具，SandboxExecWorker 只能访问 run/report 工具 |
| **MCP 进程隔离** | `mcp_server.py` | 工具运行在独立进程，Agent 以 MCP Client 身份经 stdio 调用 |

---

## 快速开始

### 1. 环境准备

- Python 3.12+
- [Ollama](https://ollama.com/) 运行本地 llama3.1

```bash
ollama pull llama3.1
ollama serve
```

### 2. 安装依赖

```bash
uv venv
.venv\Scripts\activate  # Windows；Linux/Mac: source .venv/bin/activate
uv pip install -e .
```

### 3. 启动 Mock 后端（可选，演示用）

```bash
python mock_server.py
# API: http://127.0.0.1:8080/api
# Swagger UI: http://127.0.0.1:8080/swagger-ui/swagger-ui-5.32.12/dist/index.html
# OpenAPI: http://127.0.0.1:8080/openapi.yaml
```

### 4. 启动 Agent

```bash
streamlit run final_agent.py
```

### 5. 自愈 Demo 玩法

1. 启动 Mock 后端，在 Streamlit 输入 `拉取 http://127.0.0.1:8080/openapi.yaml 接口契约，生成pytest测试脚本并沙箱执行` —— 应全部通过
2. 修改 `mock_server.py` 任意接口的返回字段名（如把 `msg` 改成 `message`）
3. 重启 Mock，再次跑同样指令 —— 测试会因断言失败触发自愈循环，Agent 自动修复代码

---

## 项目结构

```text
.
├── final_agent.py              # 主入口（streamlit run 多智能体）
├── ui.py                       # Streamlit UI（set_page_config + render_ui）
├── agents/                     # 多智能体节点模块
│   ├── state.py                # 共享状态 AgentState + 代码清洗
│   ├── mcp_tools.py            # MCP 适配器 + Pydantic schemas + 工具列表
│   ├── diag_repair.py          # Worker1：测试代码生成 & 诊断修复
│   ├── sandbox_exec.py         # Worker2：沙箱执行 & 结果采集
│   ├── supervisor.py           # Supervisor + self_heal_check + finish_node
│   └── graph.py                # build_app() 构建 LangGraph 工作图
├── mcp_server.py               # FastMCP 工具服务器（5 个工具）
├── mock_server.py              # Flask Mock 后端 + 5 个用户接口 + Swagger UI
├── swagger_openapi/            # OpenAPI 契约 + Swagger UI 静态资源
├── tests/                      # 生成的 pytest 测试代码（test_generated.py）
├── multi_agent_memory.sqlite   # LangGraph checkpoint + 自愈历史 DB
└── pyproject.toml
```

---

## 可观测性（LangSmith）

```bash
set LANGCHAIN_TRACING_V2=true
set LANGCHAIN_API_KEY=your-api-key
```

可视化 Supervisor 路由决策链与 Worker 工具调用链。

---

## 技术栈

Python · LangGraph · LangChain · MCP 协议 · Ollama (llama3.1) · FastMCP · Streamlit · SQLite · pytest · Flask · OpenAPI/Swagger

---

## 安全扫描（Semgrep Skill）

项目内嵌 Claude Code Skill `.claude/skills/semgrep-scan/`，运行 Semgrep Pro SAST 扫描并生成 HTML 报告：

```
/semgrep-scan
/semgrep-scan --config p/owasp-top-ten
```

Skill 只读，不修改源码。
