#!/usr/bin/env python3
"""Build a QtCore payload test driver from pinned public VESC Tool sources.

Use --offline for verified cached files, or --source-repo PATH to read the
pinned revision from an existing local Git checkout without changing it.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess

from vesc_sources import BUILD, CACHE, LOCK, ROOT, prepare, sha

METHODS = (
    'QString CodeLoader::reduceLispFile(',
    'QByteArray CodeLoader::lispPackImports(',
    'QPair<QString, QList<QPair<QString, QByteArray> > > CodeLoader::lispUnpackImports(',
    'bool CodeLoader::getImportFromLine(',
)


def method_span(source: bytes, signature: str) -> tuple[int, int]:
    start = source.index(signature.encode())
    pos = source.index(b'{', start)
    depth = 0
    while pos < len(source):
        if source[pos:pos + 2] == b'//':
            pos = source.index(b'\n', pos) + 1
            continue
        if source[pos:pos + 2] == b'/*':
            pos = source.index(b'*/', pos) + 2
            continue
        char = source[pos]
        if char in (34, 39):
            quote = char
            pos += 1
            while source[pos] != quote:
                pos += 2 if source[pos] == 92 else 1
            pos += 1
            continue
        if char == 123:
            depth += 1
        elif char == 125:
            depth -= 1
            if depth == 0:
                return start, pos + 1
        pos += 1
    raise ValueError('Unclosed C++ function')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--offline', action='store_true')
    parser.add_argument('--source-repo', type=Path)
    args = parser.parse_args()
    sources = prepare(source_repo=args.source_repo, offline=args.offline)
    build = BUILD
    build.mkdir(parents=True, exist_ok=True)
    source = (sources / 'codeloader.cpp').read_bytes()
    notice = source[:source.index(b'#include')]
    bodies = [notice]
    spans = []
    for signature in METHODS:
        start, end = method_span(source, signature)
        bodies.append(source[start:end] + b'\n')
        spans.append({'signature': signature, 'start_byte': start, 'end_byte': end,
                      'first_line': source[:start].count(b'\n') + 1,
                      'sha256': sha(source[start:end])})
    (build / 'vesc_methods.inc').write_bytes(b'\n'.join(bodies))
    headers = subprocess.check_output(['qmake', '-query', 'QT_INSTALL_HEADERS'], text=True).strip()
    libraries = subprocess.check_output(['qmake', '-query', 'QT_INSTALL_LIBS'], text=True).strip()
    executable = build / 'vesc-payload-host'
    command = ['g++', '-std=c++17', '-O2', '-fPIC', '-no-pie',
               str(ROOT / 'tests/vesc_payload_host.cpp'), str(sources / 'vbytearray.cpp'),
               '-I' + str(sources), '-I' + str(build), '-I' + headers, '-I' + headers + '/QtCore',
               '-L' + libraries, '-lQt5Core', '-o', str(executable)]
    temporary = CACHE / 'tmp'
    temporary.mkdir(exist_ok=True)
    print('Building the pinned VESC Tool pack/unpack methods with QtCore; one compiler job', flush=True)
    subprocess.run(command, cwd=ROOT, env={**os.environ, 'TMPDIR': str(temporary)}, check=True)
    manifest = {'vesc_tool_commit': LOCK['commit'], 'source_hashes': LOCK['files'],
                'methods': spans, 'command': command, 'binary_sha256': sha(executable.read_bytes()),
                'driver_sha256': sha((ROOT / 'tests/vesc_payload_host.cpp').read_bytes()),
                'qt_version': subprocess.check_output(['qmake', '-query', 'QT_VERSION'], text=True).strip(),
                'network': 'No network/transport linked; driver enforces seccomp', 'jobs': 1}
    (build / 'build-info.json').write_text(json.dumps(manifest, indent=2) + '\n')


if __name__ == '__main__':
    main()
