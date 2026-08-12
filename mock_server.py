"""
Flask Mock 后端 - 基于 openapi.yaml 实现 5 个用户管理接口
启动：python mock_server.py
访问：http://127.0.0.1:8080/api/user/login 等

【自愈 Demo 玩法】
1. 先正常启动，跑 Agent 生成测试代码并执行（应全部通过）
2. 修改下方任意接口的返回字段名（如把 msg 改成 message）
3. 重新跑 Agent，测试会因断言失败触发自愈循环，Agent 自动修复代码
"""
from flask import Flask, request, jsonify, send_from_directory
import os

app = Flask(__name__)

# ==================== Mock 数据存储 ====================
users = {
    "1": {"id": 1, "name": "张三", "phone": "13800138000", "age": 25},
    "2": {"id": 2, "name": "李四", "phone": "13800138001", "age": 30},
}
next_id = 3
tokens = {}  # username -> token


# ==================== API 接口实现 ====================

@app.route('/api/user/login', methods=['POST'])
def login():
    """用户登录"""
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    if username == 'test01' and password == '123456':
        token = 'mock-jwt-token-' + username
        tokens[username] = token
        return jsonify({"code": 200, "msg": "登录成功", "data": {"token": token}})
    return jsonify({"code": 401, "msg": "用户名或密码错误", "data": None})


@app.route('/api/user/info', methods=['GET'])
def get_info():
    """获取登录用户详情"""
    auth = request.headers.get('Authorization', '')
    if not auth.startswith('Bearer '):
        return jsonify({"code": 401, "msg": "未授权", "data": None})
    token = auth[7:]
    for username, t in tokens.items():
        if t == token:
            return jsonify({"code": 200, "msg": "请求成功", "data": {"username": username, "role": "admin"}})
    return jsonify({"code": 401, "msg": "token无效", "data": None})


@app.route('/api/user/add', methods=['POST'])
def add_user():
    """新增用户"""
    auth = request.headers.get('Authorization', '')
    if not auth.startswith('Bearer '):
        return jsonify({"code": 401, "msg": "未授权", "data": None})
    data = request.get_json()
    global next_id
    new_user = {
        "id": next_id,
        "name": data.get('name'),
        "phone": data.get('phone'),
        "age": data.get('age', 0)
    }
    users[str(next_id)] = new_user
    next_id += 1
    return jsonify({"code": 200, "msg": "添加成功", "data": new_user})


@app.route('/api/user/delete/<int:id>', methods=['DELETE'])
def delete_user(id):
    """删除用户"""
    auth = request.headers.get('Authorization', '')
    if not auth.startswith('Bearer '):
        return jsonify({"code": 401, "msg": "未授权", "data": None})
    if str(id) in users:
        del users[str(id)]
        return jsonify({"code": 200, "msg": "删除成功", "data": None})
    return jsonify({"code": 404, "msg": "用户不存在", "data": None})


@app.route('/api/user/list', methods=['GET'])
def list_users():
    """分页查询用户列表"""
    auth = request.headers.get('Authorization', '')
    if not auth.startswith('Bearer '):
        return jsonify({"code": 401, "msg": "未授权", "data": None})
    page_num = int(request.args.get('pageNum', 1))
    page_size = int(request.args.get('pageSize', 10))
    keyword = request.args.get('keyword', '')

    filtered = list(users.values())
    if keyword:
        filtered = [u for u in filtered if keyword in u.get('name', '')]

    total = len(filtered)
    start = (page_num - 1) * page_size
    end = start + page_size
    page_data = filtered[start:end]

    return jsonify({"code": 200, "msg": "请求成功", "data": {"total": total, "list": page_data}})


# ==================== 静态文件服务（Swagger UI + openapi.yaml）====================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SWAGGER_DIR = os.path.join(BASE_DIR, 'swagger_openapi')


@app.route('/openapi.yaml')
def serve_openapi():
    return send_from_directory(SWAGGER_DIR, 'openapi.yaml')


@app.route('/swagger-ui/<path:path>')
def serve_swagger(path):
    return send_from_directory(os.path.join(SWAGGER_DIR, 'swagger-ui'), path)


if __name__ == '__main__':
    print("=" * 60)
    print("Flask Mock 后端已启动")
    print(f"  API 基地址:  http://127.0.0.1:8080/api")
    print(f"  Swagger UI:  http://127.0.0.1:8080/swagger-ui/swagger-ui-5.32.12/dist/index.html")
    print(f"  OpenAPI文档: http://127.0.0.1:8080/openapi.yaml")
    print("=" * 60)
    app.run(host='127.0.0.1', port=8080, debug=True)
