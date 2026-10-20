#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""跨境电商 ERP —— PostgreSQL 数据库备份脚本。

通过 ``docker exec`` 调用数据库容器内的 ``pg_dump``，导出 custom 格式（``-Fc``）
的备份文件到 ``backend/backups/``，文件名形如 ``erp_20261008_201000.dump``。

用法::

    python scripts/backup_db.py                 # 默认输出到 backend/backups/
    python scripts/backup_db.py --out-dir D:/bak
    python scripts/backup_db.py --keep 10       # 保留最近 10 份，清理更旧的

连接信息全部从 ``backend/.env`` 读取，不在代码中硬编码任何密码。
本脚本既可直接运行，也可被 import 后调用 :func:`run_backup`。
"""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlparse

BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV_FILE = BACKEND_ROOT / ".env"
DEFAULT_OUT_DIR = BACKEND_ROOT / "backups"
DEFAULT_CONTAINER = "crossborder-erp-db-1"
FILE_PREFIX = "erp"
FILE_SUFFIX = ".dump"
SAFE_DELETE_LIMIT = 50  # safe-delete 守卫：单次最多删除的文件数


# --------------------------------------------------------------------------- #
# 配置读取
# --------------------------------------------------------------------------- #
def load_env_file(path: Path) -> Dict[str, str]:
    """解析 .env 文件（KEY=VALUE），忽略空行与 # 注释。"""
    env: Dict[str, str] = {}
    if not path.is_file():
        raise FileNotFoundError(f"未找到环境文件: {path}")
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip().strip('"').strip("'")
        env[key.strip()] = value
    return env


def resolve_db_settings(env: Dict[str, str]) -> Dict[str, str]:
    """从环境变量字典中解析出数据库连接参数。

    优先解析 ``DATABASE_URL``（形如 ``postgresql+psycopg://user:pwd@host:port/db``），
    缺失时回退到 ``POSTGRES_USER / POSTGRES_PASSWORD / POSTGRES_DB``。
    """
    url = env.get("DATABASE_URL")
    if url:
        parsed = urlparse(url)
        # SQLAlchemy 的 postgresql+psycopg:// 前缀需要去掉 driver 部分
        scheme = parsed.scheme.split("+")[0]
        if scheme != "postgresql":
            raise ValueError(f"DATABASE_URL 不是 PostgreSQL 连接串: {url}")
        if not parsed.hostname or not parsed.path.lstrip("/"):
            raise ValueError(f"DATABASE_URL 缺少主机或库名: {url}")
        return {
            "user": parsed.username or "",
            "password": parsed.password or "",
            "host": parsed.hostname,
            "port": str(parsed.port or 5432),
            "dbname": parsed.path.lstrip("/"),
        }

    user = env.get("POSTGRES_USER")
    dbname = env.get("POSTGRES_DB")
    if not user or not dbname:
        raise ValueError(".env 中既无 DATABASE_URL，也缺少 POSTGRES_USER/POSTGRES_DB")
    return {
        "user": user,
        "password": env.get("POSTGRES_PASSWORD", ""),
        "host": "127.0.0.1",
        "port": "5432",
        "dbname": dbname,
    }


# --------------------------------------------------------------------------- #
# 备份执行
# --------------------------------------------------------------------------- #
def build_dump_argv(
    container: str,
    settings: Dict[str, str],
    dump_format: str = "custom",
) -> List[str]:
    """构造 docker exec + pg_dump 的命令参数列表（密码通过环境变量传递）。"""
    fmt_flag = {"custom": "-Fc", "plain": "-Fp", "tar": "-Ft"}[dump_format]
    return [
        "docker", "exec",
        "-e", f"PGPASSWORD={settings['password']}",
        container,
        "pg_dump",
        "-U", settings["user"],
        "-d", settings["dbname"],
        fmt_flag,
    ]


def sha256_of(path: Path) -> str:
    """计算文件 SHA-256（大文件分块读取）。"""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_dump_file(
    path: Path,
    container: str,
    settings: Dict[str, str],
) -> int:
    """用 ``pg_restore -l`` 读取备份文件的目录（TOC），返回条目数量。

    能列出 TOC 说明文件结构完整、可被 pg_restore 识别。
    """
    argv = [
        "docker", "exec", "-i",
        "-e", f"PGPASSWORD={settings['password']}",
        container,
        "pg_restore", "-l", "-U", settings["user"],
    ]
    with path.open("rb") as handle:
        proc = subprocess.run(argv, stdin=handle, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(
            "备份文件校验失败（pg_restore -l 返回非零）: "
            + proc.stderr.decode("utf-8", "replace")
        )
    toc_lines = [
        line for line in proc.stdout.decode("utf-8", "replace").splitlines()
        if line.strip() and not line.startswith(";")
    ]
    return len(toc_lines)


def run_backup(
    out_dir: Path = DEFAULT_OUT_DIR,
    env_file: Path = DEFAULT_ENV_FILE,
    container: str = DEFAULT_CONTAINER,
    dump_format: str = "custom",
    keep: Optional[int] = None,
    timestamp: Optional[datetime] = None,
    verbose: bool = True,
) -> Path:
    """执行一次备份，返回生成的备份文件路径。

    :param keep: 保留最近 N 份备份；``None``（默认）表示不做任何清理。
    """
    settings = resolve_db_settings(load_env_file(Path(env_file)))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    timestamp = timestamp or datetime.now()
    filename = f"{FILE_PREFIX}_{timestamp.strftime('%Y%m%d_%H%M%S')}{FILE_SUFFIX}"
    target = out_dir / filename

    argv = build_dump_argv(container, settings, dump_format)
    if verbose:
        printable = [a if not a.startswith("PGPASSWORD=") else "PGPASSWORD=***" for a in argv]
        print(f"[backup] 执行命令: {' '.join(printable)} > {target}")

    # pg_dump 默认输出到 stdout，这里以二进制方式捕获后落盘
    proc = subprocess.run(argv, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(
            "pg_dump 执行失败: " + proc.stderr.decode("utf-8", "replace")
        )
    target.write_bytes(proc.stdout)

    size = target.stat().st_size
    if size == 0:
        raise RuntimeError(f"备份文件为空，请检查 pg_dump 输出: {target}")

    checksum = sha256_of(target)
    toc_count = verify_dump_file(target, container, settings)

    if verbose:
        print(f"[backup] 备份文件: {target}")
        print(f"[backup] 文件大小: {size} 字节 ({size / 1024:.1f} KiB)")
        print(f"[backup] SHA-256 : {checksum}")
        print(f"[backup] 校验通过: pg_restore -l 列出 {toc_count} 个对象")

    if keep is not None:
        removed = prune_backups(out_dir, keep, verbose=verbose)
        if verbose and removed:
            print(f"[backup] 已清理 {len(removed)} 个旧备份")

    return target


def list_backups(out_dir: Path) -> List[Path]:
    """列出备份目录下所有备份文件，按修改时间从新到旧排序。"""
    out_dir = Path(out_dir)
    if not out_dir.is_dir():
        return []
    files = [
        p for p in out_dir.iterdir()
        if p.is_file()
        and p.name.startswith(FILE_PREFIX + "_")
        and p.name.endswith(FILE_SUFFIX)
    ]
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)


def prune_backups(out_dir: Path, keep: int, verbose: bool = True) -> List[Path]:
    """只保留最近 keep 份备份，删除更旧的文件（逐个 os.remove，不批量删目录）。"""
    if keep < 1:
        raise ValueError("--keep 必须 >= 1")
    files = list_backups(out_dir)
    doomed = files[keep:]
    if len(doomed) > SAFE_DELETE_LIMIT:
        raise RuntimeError(
            f"待删除文件数 {len(doomed)} 超过安全上限 {SAFE_DELETE_LIMIT}，"
            "已中止清理，请手工确认后处理。"
        )
    removed: List[Path] = []
    for path in doomed:
        if verbose:
            print(f"[backup] 删除旧备份: {path}")
        os.remove(path)  # 单文件删除，safe-delete 守卫允许
        removed.append(path)
    return removed


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="备份 ERP PostgreSQL 数据库（容器内 pg_dump，custom 格式）"
    )
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR),
                        help=f"备份输出目录（默认 {DEFAULT_OUT_DIR}）")
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_FILE),
                        help=f".env 路径（默认 {DEFAULT_ENV_FILE}）")
    parser.add_argument("--container", default=DEFAULT_CONTAINER,
                        help=f"数据库容器名（默认 {DEFAULT_CONTAINER}）")
    parser.add_argument("--format", dest="dump_format", default="custom",
                        choices=["custom", "plain", "tar"],
                        help="pg_dump 输出格式（默认 custom，即 -Fc）")
    parser.add_argument("--keep", type=int, default=None,
                        help="仅保留最近 N 份备份，删除更旧的；默认不清理")
    parser.add_argument("--quiet", action="store_true", help="减少输出")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    verbose = not args.quiet
    try:
        run_backup(
            out_dir=Path(args.out_dir),
            env_file=Path(args.env_file),
            container=args.container,
            dump_format=args.dump_format,
            keep=args.keep,
            verbose=verbose,
        )
    except Exception as exc:  # noqa: BLE001 - CLI 顶层统一报错
        print(f"[backup] 失败: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
