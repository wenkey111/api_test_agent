"""接口测试自愈 Agent —— 主入口。

启动方式：
    streamlit run final_agent.py

结构：
    agents/        多智能体节点模块（state/mcp_tools/diag_repair/sandbox_exec/supervisor/graph）
    ui.py          Streamlit UI（set_page_config + render_ui）
    mcp_server.py  FastMCP 工具服务器
    mock_server.py Flask Mock 后端
"""
# 必须最先 import ui，使 st.set_page_config 成为第一个 streamlit 命令
from ui import render_ui
import streamlit as st
from agents.graph import build_app


# 构建并编译 LangGraph 工作图（带 SQLite checkpoint）
# 用 @st.cache_resource 缓存，避免每次 rerun 重复创建 SQLite 连接导致泄漏/锁冲突
@st.cache_resource
def get_app():
    return build_app()


app = get_app()

# 渲染 Streamlit 界面
render_ui(app)
