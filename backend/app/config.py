import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_env():
    path = ROOT / '.env'
    if path.exists():
        for line in path.read_text(encoding='utf-8').splitlines():
            if line.strip() and not line.lstrip().startswith('#'):
                key, value = line.split('=', 1)
                os.environ.setdefault(key.strip(), value.strip())


load_env()


def database_url():
    value = os.getenv('DATABASE_URL')
    if not value:
        raise RuntimeError('请先按 .env.example 创建 backend/.env 并配置 DATABASE_URL')
    return value
