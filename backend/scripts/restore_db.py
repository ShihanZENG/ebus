#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""跨境电商 ERP —— PostgreSQL 数据库恢复脚本。

从 ``backup_db.py`` 生成的备份文件恢复到**指定的目标库**。为防止误覆盖，
``--target-db`` 为必填项；当目标库名与源库（.env 中的库）相同时，默认拒绝执行，
必须再显式加 ``--force``。

用法::

    # 演练：恢复到临时库（推荐先建库）
    docker exec -e PGPASSWORD=*** <container> createdb -U erp erp_restore_test
    python scripts/restore_db.py backups/erp_20261008_201000.dump --target-db erp_restore_test

    # 只打印将要执行的命令，不真正执行
    python scripts/restore_db.py backups/erp_xxx.dump --target-db erp_restore_test --dry-run

连接信息从 ``backend/.env`` 读取，不在代码中硬编码任何密码。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional

BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV_FILE = BACKEND_ROOT / ".env"
DEFAULT_CONTAINER = "crossborder-erp-db-1"
DEFAULT_BACKUP_DIR = BACKEND_ROOT / "backups"

# 恢复后用于一致性校验的关键表
VERIFY_TABLES = [
    "products",
    "skus",
    "sales_orders",
    "purchase_orders",
    "inventory_balances",
]


# --------------------------------------------------------------------------- #
# 复用 backup_db.py 的配置读取逻辑（保持单一来源）
# --------------------------------------------------------------------------- #
def _load_helpers():
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import backup_db  # noqa: WPS433 - 脚本间复用

    return backup_db


def load_settings(env_file: Path) -> Dict[str, str]:
    helpers = _load_helpers()
    return helpers.resolve_db_settings(helpers.load_env_file(Path(env_file)))


# --------------------------------------------------------------------------- #
# 目标库检查
# --------------------------------------------------------------------------- #
def psql_scalar(container: str, settings: Dict[str, str], sql: str, dbname: str = "postgres") -> str:
    """在容器内执行一条返回单值的 SQL，返回去空格后的字符串。"""
    argv = [
        "docker", "exec",
        "-e", f"PGPASSWORD={settings['password']}",
        container,
        "psql", "-U", settings["user"], "-d", dbname, "-t", "-A", "-c", sql,
    ]
    proc = subprocess.run(argv, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(
            "psql 执行失败: " + proc.stderr.decode("utf-8", "replace")
        )
    return proc.stdout.decode("utf-8", "replace").strip()


def database_exists(container: str, settings: Dict[str, str], dbname: str) -> bool:
    sql = f"select 1 from pg_database where datname = '{dbname}';"
    return psql_scalar(container, settings, sql) == "1"


def build_createdb_hint(container: str, settings: Dict[str, str], dbname: str) -> str:
    return (
        f"目标库 '{dbname}' 不存在。请先创建：\n"
        f"  docker exec -e PGPASSWORD=*** {container} "
        f"createdb -U {settings['user']} {dbname}\n"
        f"或为本脚本加 --create-db 参数自动创建。"
    )


def build_restore_argv(
    container: str,
    settings: Dict[str, str],
    target_db: str,
    clean: bool,
    jobs: int,
) -> List[str]:
    """构造 docker exec + pg_restore 命令（备份文件通过 stdin 传入）。"""
    argv = [
        "docker", "exec", "-i",
        "-e", f"PGPASSWORD={settings['password']}",
        container,
        "pg_restore",
        "-U", settings["user"],
        "-d", target_db,
        "--no-owner",
    ]
    if clean:
        # --clean --if-exists 会先 DROP 目标库中已存在的同名对象，谨慎使用
        argv += ["--clean", "--if-exists"]
    if jobs > 1:
        argv += ["-j", str(jobs)]
    return argv


def print_argv(argv: List[str]) -> str:
    return " ".join(a if not a.startswith("PGPASSWORD=") else "PGPASSWORD=***" for a in argv)


def count_rows(container: str, settings: Dict[str, str], dbname: str, tables: List[str]) -> Dict[str, int]:
    """统计指定库中各表的行数；表不存在时返回 -1。"""
    result: Dict[str, int] = {}
    for table in tables:
        exists_sql = (
            "select 1 from information_schema.tables "
            f"where table_schema='public' and table_name='{table}';"
        )
        if psql_scalar(container, settings, exists_sql, dbname=dbname) != "1":
            result[table] = -1
            continue
        raw = psql_scalar(container, settings, f'select count(*) from "{table}";', dbname=dbname)
        result[table] = int(raw) if raw.isdigit() else -1
    return result


def verify_backup_file(path: Path, container: str, settings: Dict[str, str]) -> int:
    """用 pg_restore -l 确认备份文件可读，返回 TOC 条目数。"""
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
            "备份文件不可用（pg_restore -l 失败）: "
            + proc.stderr.decode("utf-8", "replace")
        )
    return len([
        line for line in proc.stdout.decode("utf-8", "replace").splitlines()
        if line.strip() and not line.startswith(";")
    ])


# --------------------------------------------------------------------------- #
# 恢复主流程
# --------------------------------------------------------------------------- #
def run_restore(
    backup_file: Path,
    target_db: Optional[str],
    env_file: Path = DEFAULT_ENV_FILE,
    container: str = DEFAULT_CONTAINER,
    create_db: bool = False,
    clean: bool = False,
    jobs: int = 1,
    dry_run: bool = False,
    force: bool = False,
    verify: bool = False,
    verbose: bool = True,
) -> int:
    settings = load_settings(env_file)
    backup_file = Path(backup_file)

    if not target_db:
        raise ValueError("必须显式指定 --target-db，拒绝在未明确目标库的情况下恢复。")

    # 安全护栏：默认禁止恢复到源库（.env 中的数据库）
    if target_db == settings["dbname"] and not force:
        raise ValueError(
            f"目标库 '{target_db}' 与源库同名，恢复会覆盖现有数据。"
            f"如确需覆盖，请显式追加 --force（建议先备份当前库）。"
        )

    if not backup_file.is_file():
        raise FileNotFoundError(f"备份文件不存在: {backup_file}")
    if backup_file.stat().st_size == 0:
        raise ValueError(f"备份文件为空: {backup_file}")

    argv = build_restore_argv(container, settings, target_db, clean, jobs)
    if verbose:
        print(f"[restore] 备份文件: {backup_file} ({backup_file.stat().st_size} 字节)")
        print(f"[restore] 目标库  : {target_db}（容器 {container}）")
        print(f"[restore] 将执行  : {print_argv(argv)} < {backup_file.name}")

    if dry_run:
        print("[restore] --dry-run 模式，未执行任何写操作。")
        if not database_exists(container, settings, target_db):
            print("[restore] 提示：" + build_createdb_hint(container, settings, target_db))
        return 0

    toc_count = verify_backup_file(backup_file, container, settings)
    if verbose:
        print(f"[restore] 备份文件校验通过，TOC 条目 {toc_count} 个")

    if not database_exists(container, settings, target_db):
        if not create_db:
            raise RuntimeError(build_createdb_hint(container, settings, target_db))
        createdb_argv = [
            "docker", "exec",
            "-e", f"PGPASSWORD={settings['password']}",
            container,
            "createdb", "-U", settings["user"], target_db,
        ]
        if verbose:
            print(f"[restore] 创建目标库: {print_argv(createdb_argv)}")
        proc = subprocess.run(createdb_argv, capture_output=True)
        if proc.returncode != 0:
            raise RuntimeError(
                "createdb 失败: " + proc.stderr.decode("utf-8", "replace")
            )

    with backup_file.open("rb") as handle:
        proc = subprocess.run(argv, stdin=handle, capture_output=True)

    stderr = proc.stderr.decode("utf-8", "replace")
    if proc.returncode != 0:
        # pg_restore 对「对象已存在」等错误返回非零但可能已部分恢复，这里明确报错
        raise RuntimeError(f"pg_restore 退出码 {proc.returncode}:\n{stderr}")
    if stderr.strip():
        print(f"[restore] pg_restore 警告信息:\n{stderr}")
    if verbose:
        print(f"[restore] 恢复完成：{backup_file.name} -> {target_db}")

    if verify:
        counts = count_rows(container, settings, target_db, VERIFY_TABLES)
        if verbose:
            print(f"[restore] 目标库 {target_db} 关键表行数：")
            for table, rows in counts.items():
                print(f"    {table:<20} {rows}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="从备份文件恢复到指定的 PostgreSQL 目标库"
    )
    parser.add_argument("backup_file", nargs="?", default=None,
                        help=f"备份文件路径；省略时自动取 backups/ 下最新一份")
    parser.add_argument("--target-db", required=True,
                        help="目标库名（必填，防止误覆盖）")
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_FILE), help=".env 路径")
    parser.add_argument("--container", default=DEFAULT_CONTAINER, help="数据库容器名")
    parser.add_argument("--create-db", action="store_true",
                        help="目标库不存在时自动 createdb")
    parser.add_argument("--clean", action="store_true",
                        help="pg_restore 加 --clean --if-exists（会 DROP 目标库同名对象）")
    parser.add_argument("--jobs", type=int, default=1, help="并行恢复工作数（默认 1）")
    parser.add_argument("--dry-run", action="store_true", help="只打印将执行的命令")
    parser.add_argument("--force", action="store_true",
                        help="允许恢复到与源库同名的库（危险）")
    parser.add_argument("--verify", action="store_true",
                        help="恢复后打印关键表行数")
    parser.add_argument("--quiet", action="store_true", help="减少输出")
    return parser


def _resolve_latest_backup() -> Path:
    helpers = _load_helpers()
    files = helpers.list_backups(DEFAULT_BACKUP_DIR)
    if not files:
        raise FileNotFoundError(f"未找到任何备份文件: {DEFAULT_BACKUP_DIR}")
    return files[0]


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    backup_file = Path(args.backup_file) if args.backup_file else _resolve_latest_backup()
    try:
        return run_restore(
            backup_file=backup_file,
            target_db=args.target_db,
            env_file=Path(args.env_file),
            container=args.container,
            create_db=args.create_db,
            clean=args.clean,
            jobs=args.jobs,
            dry_run=args.dry_run,
            force=args.force,
            verify=args.verify,
            verbose=not args.quiet,
        )
    except Exception as exc:  # noqa: BLE001 - CLI 顶层统一报错
        print(f"[restore] 失败: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
