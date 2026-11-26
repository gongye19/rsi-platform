"""Import a pinned full-corpus text index without transferring the raw PDFs."""
from __future__ import annotations
import fcntl
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
from contextlib import closing

from harnesslens.core.artifacts import write_json
from .adapter import ROOT, asset_manifest
from .data import rows, sha
from .download import valid, safe_target


def prepare_runtime(root, index_target, *, repo_root=ROOT):
    root, index_target, repo_root = Path(root), Path(index_target), Path(repo_root)
    manifest = asset_manifest(repo_root)
    pin_path = repo_root / 'configs/fdabench-runtime-index.json'
    pin = json.loads(pin_path.read_text())
    if pin.get('schema') != 'rsi.fdabench-runtime-index.v1' or pin['assets_sha256'] != sha(repo_root/'configs/fdabench-assets.json'):
        raise ValueError('Prebuilt index source pins changed')
    for item in manifest['databases']:
        if not valid(safe_target(root,item['local_path']),item):
            raise ValueError('Database missing or changed: '+item['db'])
    source = root / 'prebuilt/documents.sqlite'
    if source.stat().st_size != pin['bytes'] or sha(source) != pin['index']['index_sha256']:
        raise ValueError('Prebuilt document index checksum mismatch')
    with closing(sqlite3.connect(f'file:{source.resolve()}?mode=ro',uri=True)) as connection:
        if connection.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise ValueError('Prebuilt index integrity check failed')
        counts = connection.execute('SELECT count(distinct path),count(*) FROM chunks').fetchone()
        if counts != (pin['pdf_count'],pin['chunks']):
            raise ValueError('Prebuilt index corpus coverage differs from source pins')
    for key, path in [('public_tasks','tasks/tasks.jsonl'),('references','evaluation/references.jsonl')]:
        value = hashlib.sha256(json.dumps(rows(root/path),sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
        if value != manifest[key+'_canonical_sha256']:
            raise ValueError('Pinned task/reference projection changed')
    listing = json.loads((root/'metadata/corpus_file_listing.json').read_text())
    wanted = {e['path'] for e in manifest['documents']}
    actual = sorted((e['path'],e['size'],(e.get('lfs') or {}).get('oid') or e.get('oid')) for e in listing if e['path'].lower().endswith('.pdf') or e['path'] in wanted)
    expected = sorted((e['path'],e['size'],e.get('sha256') or e.get('git_blob')) for e in manifest['documents'])
    if actual != expected:
        raise ValueError('Public corpus listing differs from the pinned sources')
    verified = {'assets_sha256': pin['assets_sha256'],
                'tasks_sha256': sha(root/'tasks/tasks.jsonl'),
                'references_sha256': sha(root/'evaluation/references.jsonl'),
                'pdf_count': pin['pdf_count'], 'database_count':len(manifest['databases']),
                'mode':'prebuilt_runtime', 'prebuilt_pin_sha256':sha(pin_path)}
    index_target.parent.mkdir(parents=True,exist_ok=True)
    with (index_target.parent/'.index.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        if index_target.exists():
            if sha(index_target) != pin['index']['index_sha256']:
                raise ValueError('Existing document index changed; choose a new index directory')
        elif source.resolve() != index_target.resolve():
            with tempfile.NamedTemporaryFile(dir=index_target.parent,prefix='.import-',delete=False) as handle:
                temporary=Path(handle.name)
                try:
                    with source.open('rb') as stream:shutil.copyfileobj(stream,handle,1024**2)
                    handle.flush()
                except BaseException:
                    temporary.unlink(missing_ok=True)
                    raise
            temporary.replace(index_target)
        write_json(root/'metadata/verified-assets.json',verified)
        receipt = {**pin['index'],'prebuilt_pin_sha256':sha(pin_path),
                   'corpus_listing_sha256':sha(root/'metadata/corpus_file_listing.json'),
                   'verified_assets_sha256':sha(root/'metadata/verified-assets.json')}
        write_json(index_target.with_name('index.json'),receipt)
    return receipt
