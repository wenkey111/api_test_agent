"""Streamlit UI：多智能体自愈系统的可视化前端。

注意：st.set_page_config 必须在所有其他 streamlit 命令前执行，
所以放在模块顶层，由 final_agent.py 在最顶部 import 时触发。
"""
import uuid

import streamlit as st


# =============================================================================
# 🎨 UI CONFIGURATION（必须在最顶部，早于任何其他 st 命令）
# =============================================================================
st.set_page_config(page_title="接口测试自愈 Agent", page_icon="🤖", layout="wide")

st.markdown("""
<style>
    :root { --bg-color: #f4f6f9; --sidebar-bg: #ffffff; --text-color: #1f2937; }
    .stApp { background-color: var(--bg-color); color: var(--text-color); }
    [data-testid="stSidebar"] { background-color: var(--sidebar-bg); }
    .status-tag { background-color: #eef2ff; color: #3b82f6; padding: 4px 8px; border-radius: 4px; font-size: 0.9rem; border: 1px solid #dbeafe; display: inline-block; margin: 2px; }
    .worker-tag { background-color: #f0fdf4; color: #15803d; border: 1px solid #bbf7d0; } /* Green for workers */
    .manager-tag { background-color: #fef2f2; color: #b91c1c; border: 1px solid #fecaca; } /* Red for manager */
</style>
""", unsafe_allow_html=True)


# =============================================================================
# 🖥️ GUI RENDER
# =============================================================================

def render_ui(app):
    """渲染多智能体 Streamlit 界面。app 为 agents.graph.build_app() 返回的 compiled graph。"""

    with st.sidebar:
        st.markdown("### 🏢 Agent Org Chart")
        st.markdown("---")
        st.markdown('<div class="status-tag manager-tag">👨‍💼 Supervisor</div>', unsafe_allow_html=True)
        st.markdown("⬇️ Manages")
        st.markdown('<div class="status-tag worker-tag">🛠️ DiagRepairWorker</div>', unsafe_allow_html=True)
        st.markdown('<div class="status-tag worker-tag">⚙️ SandboxExecWorker</div>', unsafe_allow_html=True)

        st.markdown("---")
        if st.button("Clear History", use_container_width=True):
            st.session_state.thread_id = str(uuid.uuid4())
            st.rerun()

    if "thread_id" not in st.session_state:
        st.session_state.thread_id = str(uuid.uuid4())
        st.session_state.messages = []

    st.title("🤖 接口测试自愈 Agent")
    st.markdown("**Supervisor** 调度 **DiagRepairWorker**（生成/修复测试代码）与 **SandboxExecWorker**（沙箱执行）。")

    for message in st.session_state.messages:
        role = message["role"]
        content = message["content"]

        with st.chat_message(role):
            st.markdown(content)

    if prompt := st.chat_input(
        "示例: 拉取 http://XX.yaml 接口契约，生成pytest测试脚本并沙箱执行；"
        "读取 tests/XX.py 已有测试代码，结合 http://XX.json 契约，分析代码修复后沙箱执行"
    ):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            placeholder = st.empty()
            # Initialize as a list to capture multiple answers
            final_responses = []

            # Increased recursion Limit because multi-agent hops take more steps
            config = {"configurable": {"thread_id": st.session_state.thread_id}, "recursion_limit": 100}

            with st.status("🏢 Management in progress...", expanded=True) as status:
                events = app.stream({"messages": [("user", prompt)], "requirement": prompt}, config)

                for event in events:
                    # 1. Detect who is acting based on the key in the event
                    agent_name = list(event.keys())[0]
                    state_update = event[agent_name]

                    # 2. Update Status Box
                    if agent_name == "Supervisor":
                        next_worker = state_update.get("next", "FINISH")
                        if next_worker == "FINISH":
                            st.write(f"👨‍💼 **Supervisor**: Task complete.")
                        else:
                            st.write(f"👨‍💼 **Supervisor**: Handing off to `{next_worker}`")

                    elif agent_name == "DiagRepairWorker":
                        if "messages" in state_update:
                            msg = state_update["messages"][-1]
                            if hasattr(msg, 'tool_calls') and msg.tool_calls:
                                for tc in msg.tool_calls:
                                    st.write(f"⚙️ **DiagRepairWorker**: Calling `{tc['name']}`")
                                    st.code(f"Args: {tc['args']}")
                            elif msg.content:
                                st.write(f"💬 **DiagRepairWorker**: Reporting back.")
                                final_responses.append(f"**DiagRepairWorker:** {msg.content}")
                        # 显示生成的测试代码
                        if "test_code" in state_update and state_update["test_code"]:
                            code = state_update["test_code"]
                            st.write(f"📝 **DiagRepairWorker**: 已生成/修复测试代码")
                            st.code(code[:2000], language="python")

                    elif agent_name == "SandboxExecWorker":
                        if "messages" in state_update:
                            msg = state_update["messages"][-1]
                            if hasattr(msg, 'tool_calls') and msg.tool_calls:
                                for tc in msg.tool_calls:
                                    st.write(f"⚙️ **SandboxExecWorker**: Calling `{tc['name']}`")
                                    st.code(f"Args: {tc['args']}")
                            elif msg.content:
                                st.write(f"💬 **SandboxExecWorker**: Reporting back.")
                                final_responses.append(f"**SandboxExecWorker:** {msg.content}")
                        # 显示执行结果
                        if "execution_result" in state_update and state_update["execution_result"]:
                            st.write(f"📊 **SandboxExecWorker**: 执行结果已采集")

                    elif agent_name.endswith("_Tools"):
                        st.write(f"🛠️ **Tool Output**: Received successfully.")

                    elif agent_name == "self_heal_check":
                        next_action = state_update.get("next", "FINISH")
                        retry_count = state_update.get("retry_count", 0)
                        if next_action == "RETRY":
                            st.write(f"🔄 **Self-Heal**: 测试失败，触发自愈修复（第 {retry_count}/3 次重试）→ 回到 DiagRepairWorker")
                        elif next_action == "FINISH":
                            st.write(f"🏁 **Self-Heal**: 自愈流程结束（重试次数 {retry_count}/3）")

                    elif agent_name == "finish_node":
                        if "messages" in state_update:
                            msg = state_update["messages"][-1]
                            st.write(f"📋 **Final Report**: 测试报告已生成")
                            final_responses.append(f"{msg.content}")

                status.update(label="Complete", state="complete", expanded=False)

            # Display Final Response (Combine all answers)
            if final_responses:
                full_response = "\n\n".join(final_responses)
                placeholder.markdown(full_response)
                st.session_state.messages.append({"role": "assistant", "content": full_response})
