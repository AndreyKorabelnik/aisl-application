#!/usr/bin/env python3
"""Regression: clean bank-facing archive is deterministic and contains only approved files."""
import hashlib
import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
BUILDER = APP / 'tools' / 'build_clean_delivery.py'

with tempfile.TemporaryDirectory() as tmp:
    a, b = (Path(tmp) / name for name in ('release-a.zip', 'release-b.zip'))
    for out in (a,b):
        subprocess.run([sys.executable, str(BUILDER), '--output', str(out)], check=True, stdout=subprocess.DEVNULL)
    assert a.read_bytes() == b.read_bytes(), 'ZIP must be exactly reproducible'
    with zipfile.ZipFile(a) as z:
        names = z.namelist()
        assert names == sorted(set(names)), 'Zip entries must be sorted and unique'
        assert all(not n.startswith(('tools/', 'tests/')) for n in names)
        assert 'INSTALL_RU.md' in names and 'index.html' in names
        manifest = json.loads(z.read('SHA256SUMS.json'))
        assert len(manifest['assets']) == len(names) - 1
        for name, desc in manifest['assets'].items():
            data = z.read(name)
            assert hashlib.sha256(data).hexdigest() == desc['sha256']
            assert len(data) == desc['size']
        assert all(x.startswith(('demo/',)) or '/' not in x for x in names)
    print(f'PASS: deterministic clean delivery, {len(names)} allowed members, checksum manifest')
