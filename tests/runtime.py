"""Independent VESC import preparation and execution in the native C evaluator."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
HOST = Path(os.environ.get('LISPBM_HOST', str(ROOT / '.cache/build/lispbm-host')))
IMPORT_LINE = re.compile(r'''^[ \t]*\(import[ \t]+"([^"\\\r\n]+)"[ \t]+'([a-zA-Z+*/=<>#!-][a-zA-Z0-9+*/=<>!?_-]*)\)[ \t]*(?:;[^\r\n]*)?(?:\r?\n)?$''')


@dataclass
class Prepared:
    path: Path
    imports: list[tuple[str, Path]]


def prepare(source: Path, destination: Path) -> Prepared:
    """Only the documented, standalone VESC Tool import syntax is removed.

    This deliberately does not use lbm_obf's tokenizer, graph or emitter. Raw
    dependency bytes go directly to the C host's lbm_share_array_const API.
    """
    data = source.read_bytes().decode('utf-8')
    lines, imports = [], []
    for line in data.splitlines(keepends=True):
        match = IMPORT_LINE.fullmatch(line)
        if match:
            path = Path(match[1])
            path = path if path.is_absolute() else source.parent / path
            imports.append((match[2].lower(), path.resolve(strict=True)))
            lines.append('\n')
        else:
            lines.append(line)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(''.join(lines).encode('utf-8'))
    return Prepared(destination, imports)


def run(files: list[Path], imports: list[tuple[str, Path]] = (), *, timeout: float = 15) -> str:
    if not HOST.is_file():
        raise AssertionError('Real LispBM host is required: python3 tools/bootstrap_lispbm.py --local-debian-sysroot')
    command = [str(HOST)]
    for name, path in imports:
        command.extend(['--import', name, str(path)])
    for file in files:
        command.extend(['--file', str(file)])
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise AssertionError(f'LispBM exit {result.returncode}\n{result.stdout}\n{result.stderr}')
    return result.stdout


def record(case: str, original: bytes, output: bytes, transcript: str, **details) -> None:
    directory = ROOT / '.cache/results/equivalence'
    directory.mkdir(parents=True, exist_ok=True)
    data = {'case': case, 'original_bytes': len(original), 'output_bytes': len(output),
            'original_sha256': hashlib.sha256(original).hexdigest(),
            'output_sha256': hashlib.sha256(output).hexdigest(),
            'transcript_sha256': hashlib.sha256(transcript.encode()).hexdigest(),
            'transcript': transcript, 'equivalent': True, **details}
    (directory / (case + '.json')).write_text(json.dumps(data, indent=2, sort_keys=True) + '\n')
