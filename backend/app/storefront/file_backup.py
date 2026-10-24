"""Integrity-checked local-demo backup and restore for storefront files."""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import zipfile
from datetime import datetime, timezone
from pathlib import Path

FORMAT = 'storefront-files-v1'
MAX_ENTRIES = 20_000
MAX_TOTAL_SIZE = 1024 * 1024 * 1024
MAX_MANIFEST_SIZE = 10 * 1024 * 1024
_KEY = re.compile(r'^[0-9a-f]{32}\.(?:png|jpg|jpeg|pdf)$')


def _digest_file(path: Path):
    digest, size = hashlib.sha256(), 0
    with path.open('rb') as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return size, digest.hexdigest()


def _collect_sources(media_dir: Path, support_dir: Path):
    records = []
    for kind, directory, allowed in (
        ('media', Path(media_dir), {'.png', '.jpg', '.jpeg'}),
        ('support', Path(support_dir), {'.png', '.jpg', '.jpeg', '.pdf'}),
    ):
        if not directory.exists():
            continue
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError(f'{kind} 源路径不是普通目录')
        root = directory.resolve()
        for path in root.rglob('*'):
            if path.is_symlink():
                raise ValueError(f'{kind} 目录含符号链接，拒绝打包')
            if path.is_dir():
                continue
            if not path.is_file() or path.parent != root or path.suffix.lower() not in allowed or not _KEY.fullmatch(path.name):
                raise ValueError(f'{kind} 目录含不受支持的文件：{path.name}')
            size, digest = _digest_file(path)
            maximum = 5 * 1024 * 1024 if kind == 'support' else 8 * 1024 * 1024
            if size <= 0 or size > maximum:
                raise ValueError(f'{kind} 文件大小不符合商城上传上限：{path.name}')
            records.append({'path': f'{kind}/{path.name}', 'size': size, 'sha256': digest, '_source': path})
    records.sort(key=lambda item: item['path'])
    if len(records) > MAX_ENTRIES or sum(r['size'] for r in records) > MAX_TOTAL_SIZE:
        raise ValueError('商城文件总量超过本地演示备份上限')
    return records


def create_archive(media_dir: Path, support_dir: Path, output: Path):
    output = Path(output).resolve()
    source_roots = [Path(media_dir).resolve(), Path(support_dir).resolve()]
    if any(root == output or root in output.parents for root in source_roots):
        raise ValueError('备份文件不能写入商城源文件目录内部')
    if output.suffix.lower() != '.zip':
        raise ValueError('备份文件扩展名必须为 .zip')
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise FileExistsError(f'拒绝覆盖已有备份：{output}')
    records = _collect_sources(media_dir, support_dir)
    if Path(media_dir).resolve() == Path(support_dir).resolve():
        raise ValueError('商品图片目录和客服附件目录必须分开')
    manifest = {
        'format': FORMAT,
        'created_at': datetime.now(timezone.utc).isoformat(),
        'files': [{k: v for k, v in r.items() if k != '_source'} for r in records],
    }
    temporary = output.with_name(f'.{output.name}.{os.urandom(6).hex()}.tmp')
    try:
        with zipfile.ZipFile(temporary, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
            for record in records:
                archive.write(record['_source'], record['path'])
            archive.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, sort_keys=True).encode('utf-8'))
        inspect_archive(temporary)
        if output.exists():
            raise FileExistsError(f'拒绝覆盖已有备份：{output}')
        os.link(temporary, output)
        temporary.unlink()
        if os.name == 'posix':
            output.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return manifest


def _inspect_open_archive(archive: zipfile.ZipFile):
    names = archive.namelist()
    if len(names) > MAX_ENTRIES + 1 or len(names) != len(set(names)) or 'manifest.json' not in names:
        raise ValueError('备份 ZIP 目录无效或包含重复文件名')
    manifest_info = archive.getinfo('manifest.json')
    if manifest_info.file_size > MAX_MANIFEST_SIZE:
        raise ValueError('备份清单超过大小上限')
    try:
        manifest = json.loads(archive.read('manifest.json'))
    except (UnicodeDecodeError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
        raise ValueError('备份清单无法读取') from exc
    if not isinstance(manifest, dict) or manifest.get('format') != FORMAT or not isinstance(manifest.get('files'), list):
        raise ValueError('备份格式或版本不受支持')
    if len(manifest['files']) > MAX_ENTRIES:
        raise ValueError('备份文件数量超过安全上限')
    records, expected_names, total_size = [], {'manifest.json'}, 0
    for record in manifest['files']:
        if not isinstance(record, dict):
            raise ValueError('备份清单条目无效')
        name, size, expected_hash = record.get('path'), record.get('size'), record.get('sha256')
        if not isinstance(name, str) or not isinstance(expected_hash, str):
            raise ValueError('备份清单中的路径或摘要类型无效')
        match = re.fullmatch(r'(media|support)/([0-9a-f]{32}\.(?:png|jpg|jpeg|pdf))', name)
        if not match or (match.group(1) == 'media' and match.group(2).endswith('.pdf')):
            raise ValueError('备份包含不受支持的路径')
        maximum = 5 * 1024 * 1024 if match.group(1) == 'support' else 8 * 1024 * 1024
        if type(size) is not int or size <= 0 or size > maximum or not re.fullmatch(r'[0-9a-f]{64}', expected_hash):
            raise ValueError(f'备份清单中的文件信息无效：{name}')
        if name in expected_names:
            raise ValueError('备份清单包含重复路径')
        expected_names.add(name)
        total_size += size
        if total_size > MAX_TOTAL_SIZE:
            raise ValueError('备份展开总量超过安全上限')
        try:
            info = archive.getinfo(name)
        except KeyError as exc:
            raise ValueError(f'备份文件缺失：{name}') from exc
        if info.file_size != size:
            raise ValueError(f'备份文件大小不匹配：{name}')
        digest, actual_size = hashlib.sha256(), 0
        with archive.open(info, 'r') as handle:
            while chunk := handle.read(1024 * 1024):
                actual_size += len(chunk)
                digest.update(chunk)
        if actual_size != size or digest.hexdigest() != expected_hash:
            raise ValueError(f'备份文件完整性校验失败：{name}')
        records.append(record)
    if set(names) != expected_names:
        raise ValueError('备份中存在清单未登记的文件')
    return manifest, records


def inspect_archive(archive_path: Path):
    try:
        with zipfile.ZipFile(archive_path, 'r') as archive:
            return _inspect_open_archive(archive)
    except zipfile.BadZipFile as exc:
        raise ValueError('文件不是有效 ZIP 备份') from exc


def restore_archive(archive_path: Path, media_dir: Path, support_dir: Path, *, apply=False):
    media_root, support_root = Path(media_dir), Path(support_dir)
    for root in (media_root, support_root):
        if root.exists() and root.is_symlink():
            raise ValueError(f'拒绝将附件恢复到符号链接目录：{root}')
    with zipfile.ZipFile(archive_path, 'r') as archive:
        manifest, records = _inspect_open_archive(archive)
        roots = {'media': media_root.resolve(), 'support': support_root.resolve()}
        if roots['media'] == roots['support']:
            raise ValueError('商品图片目录和客服附件目录必须分开')
        targets = []
        for record in records:
            kind, name = record['path'].split('/', 1)
            target = roots[kind] / name
            if target.parent != roots[kind]:
                raise ValueError('备份目标路径越界')
            targets.append((record, target))
        conflicts = [str(target) for _, target in targets if target.exists() or target.is_symlink()]
        if conflicts:
            raise FileExistsError('恢复会覆盖已有文件，已停止且未写入：' + ', '.join(conflicts[:5]))
        if not apply:
            return {'dry_run': True, 'files': len(records), 'bytes': sum(r['size'] for r in records),
                    'created_at': manifest.get('created_at')}
        created, created_roots = [], []
        try:
            for root in roots.values():
                if not root.exists():
                    root.mkdir(parents=True, exist_ok=True)
                    created_roots.append(root)
            for record, target in targets:
                kind, name = record['path'].split('/', 1)
                target_root = roots[kind]
                if target.exists() or target.is_symlink():
                    raise FileExistsError(f'恢复期间目标文件已出现：{target}')
                descriptor = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                created.append(target)
                digest, size = hashlib.sha256(), 0
                with os.fdopen(descriptor, 'wb') as output, archive.open(record['path'], 'r') as source:
                    while chunk := source.read(1024 * 1024):
                        output.write(chunk)
                        digest.update(chunk)
                        size += len(chunk)
                    output.flush()
                    os.fsync(output.fileno())
                if size != record['size'] or digest.hexdigest() != record['sha256']:
                    raise ValueError(f'恢复期间备份内容发生变化：{record["path"]}')
                if kind == 'support' and os.name == 'posix':
                    target.chmod(stat.S_IRUSR | stat.S_IWUSR)
        except Exception:
            for target in reversed(created):
                target.unlink(missing_ok=True)
            for root in reversed(created_roots):
                try:
                    root.rmdir()
                except OSError:
                    pass
            raise
    return {'dry_run': False, 'files': len(records), 'bytes': sum(r['size'] for r in records),
            'created_at': manifest.get('created_at')}
