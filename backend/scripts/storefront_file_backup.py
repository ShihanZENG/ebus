"""Verify, back up and restore the local-demo storefront file directories."""
from __future__ import annotations

import argparse
import os
import sys
import zipfile
from datetime import datetime
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.config import ROOT  # noqa: E402
from app.storefront.file_backup import create_archive, inspect_archive, restore_archive  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description='本地演示商城文件备份/校验/预演恢复')
    commands = parser.add_subparsers(dest='command', required=True)
    backup = commands.add_parser('backup', help='创建商城文件 ZIP 备份')
    backup.add_argument('--output', type=Path, default=None)
    backup.add_argument('--media-dir', type=Path, default=Path(os.getenv('STOREFRONT_MEDIA_DIR', ROOT / 'data' / 'storefront-media')))
    backup.add_argument('--support-dir', type=Path, default=Path(os.getenv('STOREFRONT_SUPPORT_DIR', ROOT / 'data' / 'storefront-support')))
    verify = commands.add_parser('verify', help='校验备份清单和所有文件摘要')
    verify.add_argument('archive', type=Path)
    restore = commands.add_parser('restore', help='预演恢复；传 --apply 才会创建文件')
    restore.add_argument('archive', type=Path)
    restore.add_argument('--apply', action='store_true')
    restore.add_argument('--media-dir', type=Path, default=Path(os.getenv('STOREFRONT_MEDIA_DIR', ROOT / 'data' / 'storefront-media')))
    restore.add_argument('--support-dir', type=Path, default=Path(os.getenv('STOREFRONT_SUPPORT_DIR', ROOT / 'data' / 'storefront-support')))
    args = parser.parse_args()

    if args.command == 'backup':
        output = args.output or (BACKEND_ROOT / 'backups' / f"storefront_files_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip")
        manifest = create_archive(args.media_dir, args.support_dir, output)
        print(f"备份完成：{output}；文件 {len(manifest['files'])} 个。备份含私有客服附件，请按敏感数据保护。")
    elif args.command == 'verify':
        manifest, records = inspect_archive(args.archive)
        print(f"校验通过：版本 {manifest['format']}；文件 {len(records)} 个；所有 SHA-256 匹配。")
    else:
        result = restore_archive(args.archive, args.media_dir, args.support_dir, apply=args.apply)
        prefix = '已恢复' if args.apply else '恢复预演通过，未写入'
        print(f"{prefix}：文件 {result['files']} 个，合计 {result['bytes']} 字节；备份时间 {result['created_at']}。")


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile) as exc:
        print(f'文件备份操作失败：{exc}', file=sys.stderr)
        raise SystemExit(2)
