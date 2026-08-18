"""DiagRepairWorker：测试用例生成 & 诊断修复节点。

输入 Swagger/接口描述，输出标准 pytest+requests 接口测试代码；
若提供历史报错日志，则基于报错修复测试代码。
"""
from langchain_core.messages import SystemMessage
from langchain_ollama import ChatOllama

from agents.state import AgentState, _extract_python_code
from agents.mcp_tools import diag_repair_tools


def diag_repair_node(state: AgentState):
    """Worker1：测试用例生成&诊断修复节点。
    - 初次生成：按模板输出 pytest+requests 代码
    - 自愈修复：基于报错日志针对性修复现有代码（不强制套模板）
    重写提示词为测开工程师，注入历史报错日志，代码清洗后写入 state.test_code。
    """
    execution_result = state.get("execution_result", "") or ""
    existing_code = state.get("test_code", "") or ""

    # ===== 修复模式：有报错日志 + 有现有代码 =====
    if execution_result and existing_code:
        system_prompt = (
            "你是资深测开工程师。现有测试代码执行失败，请基于报错日志精准修复。\n\n"
            "【修复规则，必须严格遵守】\n"
            "- 根据报错日志反映的接口实际返回字段调整断言，不要臆造字段；\n"
            "- 若多个用例报同一字段错误（如 KeyError: 'msg'），说明后端统一改了字段名，\n"
            "  应把所有相关断言统一改为新字段名（如 message）；\n"
            "- 常见失败原因：接口返回字段名变更（如 msg→message/code→status）、\n"
            "  状态码变更、返回结构嵌套层级变化、断言值不符；\n"
            "- 输出必须是完整的修复后测试代码（用 ```python 包裹），不能只输出 diff 或片段；\n"
            "- 禁止 import 工具函数/pytest/unittest.mock；\n"
            "- 每个 test_ 函数仍须发起真实 requests 请求并 assert 响应。\n"
        )
        messages = [SystemMessage(content=system_prompt)]
        messages.append(SystemMessage(content=f"【当前测试代码】\n```python\n{existing_code}\n```"))
        messages.append(SystemMessage(content=f"【执行报错日志】\n{execution_result}\n请基于上述报错修复测试代码，输出完整修复后代码。"))

    # ===== 生成模式：初次生成 =====
    else:
        system_prompt = (
            "你是资深测开工程师，专精 pytest + requests 接口自动化测试。\n"
            "职责：输入 Swagger/接口描述，输出标准 pytest+requests 接口测试代码。\n\n"
            "【代码模板，必须严格遵循此格式】\n"
            "```python\n"
            "import requests\n\n"
            "BASE_URL = 'http://127.0.0.1:8080/api'\n\n"
            "def test_login():\n"
            "    resp = requests.post(f'{BASE_URL}/user/login', json={'username': 'test01', 'password': '123456'})\n"
            "    assert resp.status_code == 200\n"
            "    data = resp.json()\n"
            "    assert data['code'] == 200\n"
            "    assert data['msg'] == '登录成功'\n"
            "    assert 'token' in data['data']\n"
            "    assert isinstance(data['data']['token'], str)\n"
            "    return data['data']['token']\n\n"
            "def test_user_info():\n"
            "    token = test_login()\n"
            "    resp = requests.get(f'{BASE_URL}/user/info', headers={'Authorization': f'Bearer {token}'})\n"
            "    assert resp.status_code == 200\n"
            "    data = resp.json()\n"
            "    assert data['code'] == 200\n"
            "    assert data['msg'] == '请求成功'\n"
            "    assert data['data']['username'] == 'test01'\n"
            "    assert data['data']['role'] == 'admin'\n\n"
            "def test_add_user():\n"
            "    token = test_login()\n"
            "    payload = {'name': '张三', 'phone': '13800138000', 'age': 25}\n"
            "    resp = requests.post(f'{BASE_URL}/user/add', json=payload, headers={'Authorization': f'Bearer {token}'})\n"
            "    assert resp.status_code == 200\n"
            "    data = resp.json()\n"
            "    assert data['code'] == 200\n"
            "    assert data['msg'] == '添加成功'\n"
            "    assert data['data']['name'] == '张三'\n"
            "    assert data['data']['phone'] == '13800138000'\n"
            "    assert data['data']['age'] == 25\n"
            "    assert 'id' in data['data']\n\n"
            "def test_delete_user():\n"
            "    token = test_login()\n"
            "    add_resp = requests.post(f'{BASE_URL}/user/add',\n"
            "        json={'name': '待删除', 'phone': '13900000000', 'age': 20},\n"
            "        headers={'Authorization': f'Bearer {token}'})\n"
            "    user_id = add_resp.json()['data']['id']\n"
            "    resp = requests.delete(f'{BASE_URL}/user/delete/{user_id}', headers={'Authorization': f'Bearer {token}'})\n"
            "    assert resp.status_code == 200\n"
            "    data = resp.json()\n"
            "    assert data['code'] == 200\n"
            "    assert data['msg'] == '删除成功'\n\n"
            "def test_list_users():\n"
            "    token = test_login()\n"
            "    resp = requests.get(f'{BASE_URL}/user/list',\n"
            "        params={'pageNum': 1, 'pageSize': 10, 'keyword': '张'},\n"
            "        headers={'Authorization': f'Bearer {token}'})\n"
            "    assert resp.status_code == 200\n"
            "    data = resp.json()\n"
            "    assert data['code'] == 200\n"
            "    assert data['msg'] == '请求成功'\n"
            "    assert 'total' in data['data']\n"
            "    assert 'list' in data['data']\n"
            "    assert isinstance(data['data']['list'], list)\n"
            "    assert data['data']['total'] >= 0\n"
            "```\n\n"
            "【强制规则】\n"
            "- 直接输出上述格式的完整代码，用 ```python 包裹；\n"
            "- 禁止 import 工具函数（fetch_api_spec 等是 Agent 工具，不是测试代码的依赖）；\n"
            "- 禁止用 exec() 执行字符串；\n"
            "- 禁止用 unittest.mock；\n"
            "- 禁止 import pytest（pytest 会自动发现 test_ 函数）；\n"
            "- 每个 test_ 函数必须发起真实 requests 请求并 assert 响应；\n"
            "- BASE_URL 直接硬编码为 http://127.0.0.1:8080/api；\n"
        )
        messages = [SystemMessage(content=system_prompt)] + state["messages"]

    llm = ChatOllama(model="llama3.1", temperature=0)
    llm_with_tools = llm.bind_tools(diag_repair_tools)
    result = llm_with_tools.invoke(messages)
    # 代码清洗：提取 python 代码块，写入 state.test_code
    content = result.content if isinstance(result.content, str) else str(result.content)
    code = _extract_python_code(content)
    # 仅当提取到真正的 python 代码块时才更新 test_code，避免调工具时覆盖为无意义文本
    updates = {"messages": [result]}
    if "```python" in content or (code and "def test_" in code):
        updates["test_code"] = code
    return updates
