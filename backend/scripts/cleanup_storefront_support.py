"""Prune expired storefront support attachment metadata and local files.

Dry-run is the default. Use --apply only after reviewing the candidate count.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.config import ROOT  # noqa: E402
from app.db import build_engine, sessions  # noqa: E402
from app.storefront.retention import cleanup_expired_attachments  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description='预览或清理超过30天的商城客服附件')
    parser.add_argument('--apply', action='store_true', help='实际删除过期附件及其元数据；默认仅预览')
    parser.add_argument('--directory', type=Path, default=Path(os.getenv(
        'STOREFRONT_SUPPORT_DIR', str(ROOT / 'data' / 'storefront-support'))), help='私有附件目录')
    args = parser.parse_args()
    engine = build_engine()
    try:
        with sessions(engine)() as db:
            result = cleanup_expired_attachments(db, args.directory, apply=args.apply)
        action = '已清理' if args.apply else '待清理（预览）'
        print(f"{action}: 候选 {result['eligible']}，删除 {result['removed']}，跳过 {result['deferred']}")
    finally:
        engine.dispose()


if __name__ == '__main__':
    main()
