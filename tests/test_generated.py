import requests

BASE_URL = 'http://127.0.0.1:8080/api'

def test_login():
    resp = requests.post(f'{BASE_URL}/user/login', json={'username': 'test01', 'password': '123456'})
    assert resp.status_code == 200
    data = resp.json()
    # 根据报错日志，调整断言为data['message']
    assert data['code'] == 200
    assert data['message'] == '登录成功'
    assert 'token' in data['data']
    assert isinstance(data['data']['token'], str)
    return data['data']['token']

def test_user_info():
    token = test_login()
    resp = requests.get(f'{BASE_URL}/user/info', headers={'Authorization': f'Bearer {token}'})
    assert resp.status_code == 200
    data = resp.json()
    # 根据报错日志，调整断言为data['message']
    assert data['code'] == 200
    assert data['message'] == '请求成功'
    assert data['data']['username'] == 'test01'
    assert data['data']['role'] == 'admin'

def test_add_user():
    token = test_login()
    payload = {'name': '张三', 'phone': '13800138000', 'age': 25}
    resp = requests.post(f'{BASE_URL}/user/add', json=payload, headers={'Authorization': f'Bearer {token}'})
    assert resp.status_code == 200
    data = resp.json()
    # 根据报错日志，调整断言为data['message']
    assert data['code'] == 200
    assert data['message'] == '添加成功'
    assert data['data']['name'] == '张三'
    assert data['data']['phone'] == '13800138000'
    assert data['data']['age'] == 25
    assert 'id' in data['data']

def test_delete_user():
    token = test_login()
    add_resp = requests.post(f'{BASE_URL}/user/add',
        json={'name': '待删除', 'phone': '13900000000', 'age': 20},
        headers={'Authorization': f'Bearer {token}'})
    user_id = add_resp.json()['data']['id']
    resp = requests.delete(f'{BASE_URL}/user/delete/{user_id}', headers={'Authorization': f'Bearer {token}'})
    assert resp.status_code == 200
    data = resp.json()
    # 根据报错日志，调整断言为data['message']
    assert data['code'] == 200
    assert data['message'] == '删除成功'

def test_list_users():
    token = test_login()
    resp = requests.get(f'{BASE_URL}/user/list',
        params={'pageNum': 1, 'pageSize': 10, 'keyword': '张'},
        headers={'Authorization': f'Bearer {token}'})
    assert resp.status_code == 200
    data = resp.json()
    # 根据报错日志，调整断言为data['message']
    assert data['code'] == 200
    assert data['message'] == '请求成功'
    assert 'total' in data['data']
    assert 'list' in data['data']
    assert isinstance(data['data']['list'], list)
    assert data['data']['total'] >= 0

# 执行测试
if __name__ == '__main__':
    import pytest
    pytest.main([__file__, '-v'])
