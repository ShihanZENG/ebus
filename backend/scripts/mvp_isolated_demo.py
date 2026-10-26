"""Run the storefront/ERP MVP against a disposable local SQLite database.

Usage, from backend/: python -m scripts.mvp_isolated_demo
The database is created under the OS temporary directory and removed on exit.
"""

import os
import secrets
from pathlib import Path
from tempfile import TemporaryDirectory

import uvicorn
from alembic import command
from alembic.config import Config

from app.bootstrap import bootstrap
from app.config import ROOT
from app.db import build_engine, sessions
from app.main import create_app
from app.storefront.demo import seed_catalogue


def main():
    username = 'mvp_demo_admin'
    password = 'MvpDemo-' + secrets.token_urlsafe(18)
    with TemporaryDirectory(prefix='crossborder-mvp-') as directory:
        db_file = Path(directory) / 'demo.db'
        url = 'sqlite:///' + db_file.as_posix()
        os.environ['DATABASE_URL'] = url
        config = Config(str(ROOT / 'alembic.ini'))
        command.upgrade(config, 'head')
        engine = build_engine(url)
        try:
            with sessions(engine)() as db:
                bootstrap(db, username, password, demo=False)
                seed_catalogue(db)
            print('一次性演示环境已就绪：仅监听 127.0.0.1:18081', flush=True)
            print(f'演示管理员：{username}', flush=True)
            print(f'演示密码：{password}', flush=True)
            print('关闭此进程后，临时数据库将删除。', flush=True)
            uvicorn.run(create_app(engine, storefront_enabled=True), host='127.0.0.1', port=18081)
        finally:
            engine.dispose()


if __name__ == '__main__':
    main()
