import zipfile
import subprocess
import sys
from pathlib import Path

import pytest

from app.storefront.file_backup import create_archive, inspect_archive, restore_archive


def test_archive_manifest_integrity_and_preview_restore(tmp_path):
    media, support = tmp_path / 'media-src', tmp_path / 'support-src'
    media.mkdir(); support.mkdir()
    image_key, file_key = 'a' * 32 + '.jpg', 'b' * 32 + '.pdf'
    image, attachment = b'\xff\xd8\xffdemo\xff\xd9', b'%PDF-1.4 demo'
    (media / image_key).write_bytes(image)
    (support / file_key).write_bytes(attachment)
    archive = tmp_path / 'backup.zip'

    manifest = create_archive(media, support, archive)
    checked_manifest, records = inspect_archive(archive)
    assert checked_manifest == manifest
    assert [record['path'] for record in records] == [f'media/{image_key}', f'support/{file_key}']

    new_media, new_support = tmp_path / 'restore-media', tmp_path / 'restore-support'
    preview = restore_archive(archive, new_media, new_support)
    assert preview['dry_run'] and preview['files'] == 2
    assert not new_media.exists() and not new_support.exists()
    restored = restore_archive(archive, new_media, new_support, apply=True)
    assert not restored['dry_run']
    assert (new_media / image_key).read_bytes() == image
    assert (new_support / file_key).read_bytes() == attachment


def test_restore_refuses_to_overwrite_and_writes_nothing_else(tmp_path):
    media, support = tmp_path / 'media-src', tmp_path / 'support-src'
    media.mkdir(); support.mkdir()
    key = 'c' * 32 + '.png'
    (media / key).write_bytes(b'\x89PNGdata')
    archive = tmp_path / 'backup.zip'
    create_archive(media, support, archive)
    target_media, target_support = tmp_path / 'target-media', tmp_path / 'target-support'
    target_media.mkdir()
    (target_media / key).write_bytes(b'existing')

    with pytest.raises(FileExistsError):
        restore_archive(archive, target_media, target_support, apply=True)
    assert (target_media / key).read_bytes() == b'existing'
    assert not target_support.exists()


def test_tampered_backup_fails_integrity_before_restore(tmp_path):
    media, support = tmp_path / 'media-src', tmp_path / 'support-src'
    media.mkdir(); support.mkdir()
    key = 'd' * 32 + '.jpg'
    (media / key).write_bytes(b'\xff\xd8\xfforiginal\xff\xd9')
    archive, tampered = tmp_path / 'backup.zip', tmp_path / 'tampered.zip'
    create_archive(media, support, archive)
    with zipfile.ZipFile(archive) as source, zipfile.ZipFile(tampered, 'w') as target:
        manifest = source.read('manifest.json')
        target.writestr(f'media/{key}', b'\xff\xd8\xffchanged!\xff\xd9')
        target.writestr('manifest.json', manifest)

    restore_root = tmp_path / 'restore'
    with pytest.raises(ValueError, match='完整性校验失败'):
        restore_archive(tampered, restore_root / 'media', restore_root / 'support', apply=True)
    assert not restore_root.exists()


def test_backup_refuses_existing_output_and_symlinks(tmp_path):
    media, support = tmp_path / 'media-src', tmp_path / 'support-src'
    media.mkdir(); support.mkdir()
    key = 'e' * 32 + '.png'
    (media / key).write_bytes(b'\x89PNGdata')
    archive = tmp_path / 'backup.zip'
    create_archive(media, support, archive)
    original = archive.read_bytes()
    with pytest.raises(FileExistsError):
        create_archive(media, support, archive)
    assert archive.read_bytes() == original


def test_archive_rejects_traversal_manifest_paths(tmp_path):
    archive = tmp_path / 'traversal.zip'
    with zipfile.ZipFile(archive, 'w') as target:
        target.writestr('manifest.json', '{"format":"storefront-files-v1","files":[{"path":"support/../../secret.pdf","size":5,"sha256":"' + '0' * 64 + '"}]}')
        target.writestr('support/../../secret.pdf', b'nope')
    with pytest.raises(ValueError, match='路径'):
        inspect_archive(archive)


def test_cli_backup_verify_preview_and_explicit_restore(tmp_path):
    backend = Path(__file__).resolve().parents[1]
    cli = backend / 'scripts' / 'storefront_file_backup.py'
    media, support = tmp_path / 'source-media', tmp_path / 'source-support'
    media.mkdir(); support.mkdir()
    key = 'f' * 32 + '.png'
    (media / key).write_bytes(b'\x89PNGcli')
    archive = tmp_path / 'cli-backup.zip'
    run = lambda *args: subprocess.run([sys.executable, str(cli), *map(str, args)], cwd=backend,
                                       capture_output=True)
    created = run('backup', '--output', archive, '--media-dir', media, '--support-dir', support)
    assert created.returncode == 0, created.stderr
    verified = run('verify', archive)
    assert verified.returncode == 0, verified.stderr
    target_media, target_support = tmp_path / 'target-media', tmp_path / 'target-support'
    preview = run('restore', archive, '--media-dir', target_media, '--support-dir', target_support)
    assert preview.returncode == 0, preview.stderr
    assert not target_media.exists()
    applied = run('restore', archive, '--media-dir', target_media, '--support-dir', target_support, '--apply')
    assert applied.returncode == 0, applied.stderr
    assert (target_media / key).read_bytes() == b'\x89PNGcli'
