"""Pinned public VESC Tool sources for local payload compatibility tests."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / '.cache/vesc-tool'
SOURCES = CACHE / 'sources'
BUILD = CACHE / 'build'
LOCK = json.loads((ROOT / 'tools/vesc-tool-lock.json').read_text())


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def prepare(*, source_repo: Path | None = None, offline: bool = False) -> Path:
    """Read a local Git revision or download exact, checksummed public files."""
    SOURCES.mkdir(parents=True, exist_ok=True)
    for name, expected in LOCK['files'].items():
        path = SOURCES / name
        if path.exists():
            data = path.read_bytes()
        elif source_repo is not None:
            env = {**os.environ, 'GIT_NO_LAZY_FETCH': '1', 'GIT_OPTIONAL_LOCKS': '0',
                   'GIT_TERMINAL_PROMPT': '0'}
            data = subprocess.check_output(
                ['git', '-c', 'protocol.allow=never', '-C', str(source_repo),
                 'show', LOCK['commit'] + ':' + name], env=env)
        elif offline:
            raise RuntimeError(f'Pinned source missing in offline mode: {path}')
        else:
            url = f"https://raw.githubusercontent.com/vedderb/vesc_tool/{LOCK['commit']}/{name}"
            print(f'Downloading pinned VESC Tool source: {name}', flush=True)
            with urlopen(url, timeout=45) as response:
                data = response.read()
        if sha(data) != expected:
            raise ValueError(f'Pinned VESC Tool source hash mismatch: {name}')
        if not path.exists():
            with path.open('xb') as output:
                output.write(data)
    return SOURCES
