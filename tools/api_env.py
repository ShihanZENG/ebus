"""共用的后端 API 客户端：登录 + GET/POST，短输出。"""
import json
import sys
import requests

BASE = 'http://127.0.0.1:18080'


def login():
    r = requests.post(BASE + '/api/v1/auth/login',
                      json={'username': 'admin', 'password': 'Admin@2026'}, timeout=20)
    r.raise_for_status()
    return r.json()['access_token']


class Api:
    def __init__(self, token):
        self.s = requests.Session()
        self.s.headers['Authorization'] = 'Bearer ' + token

    def get(self, path, **params):
        r = self.s.get(BASE + path, params=params, timeout=60)
        return r.status_code, (r.json() if r.headers.get('content-type', '').startswith('application/json') else r.text)

    def post(self, path, body=None):
        r = self.s.post(BASE + path, json=body if body is not None else {}, timeout=180)
        return r.status_code, (r.json() if r.headers.get('content-type', '').startswith('application/json') else r.text)


def brief(value, limit=400):
    text = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    return text if len(text) <= limit else text[:limit] + '...'


if __name__ == '__main__':
    token = login()
    api = Api(token)
    for path in sys.argv[1:]:
        status, data = api.get(path)
        print(path, status)
        print(brief(data, 1500))
