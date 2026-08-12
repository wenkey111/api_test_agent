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
    重写提示词为测开工程师，注入历史报错日志，代码清洗后写入 state.test_code。
    """
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
        "- 若提供历史报错日志，修复对应断言或请求参数。\n"
    )
    messages = [SystemMessage(content=system_prompt)] + state["messages"]
    # 注入历史报错日志，让模型修复旧代码
    if state.get("execution_result"):
        messages.append(SystemMessage(
            content=f"【历史执行报错日志】\n{state['execution_result']}\n请基于上述报错修复测试代码。"
        ))
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
