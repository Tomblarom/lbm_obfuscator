"""Run the pinned native Qt packer and validate its binary import table."""
from __future__ import annotations

import base64
import json
from pathlib import Path
import struct
import subprocess

from vesc_sources import BUILD, LOCK, ROOT, sha

HOST = BUILD / 'vesc-payload-host'


def verify_host() -> dict:
    info = json.loads((HOST.parent / 'build-info.json').read_text())
    if (info['vesc_tool_commit'] != LOCK['commit']
            or info['source_hashes'] != LOCK['files']
            or info['binary_sha256'] != sha(HOST.read_bytes())
            or info['driver_sha256'] != sha((ROOT / 'tests/vesc_payload_host.cpp').read_bytes())):
        raise ValueError('Native VESC Tool packer changed; rebuild it')
    return info


def import_lines(path: Path) -> list[dict]:
    verify_host()
    result = subprocess.run([str(HOST), 'lines', str(path)], capture_output=True, text=True, timeout=10)
    if result.returncode:
        raise ValueError(result.stderr)
    return json.loads(result.stdout)


def unpack_table(payload: bytes) -> tuple[bytes, list[dict]]:
    """Independent structural check of the firmware's offsets (flags excluded)."""
    if payload[:2] != b'\0\0':
        raise ValueError('Unexpected flags')
    end = payload.index(0, 2)
    code = payload[2:end]
    cursor = end + 1
    count = struct.unpack_from('>h', payload, cursor)[0]
    if not 0 <= count < 500:
        raise ValueError('Invalid import count')
    cursor += 2
    entries = []
    for _ in range(count):
        end_tag = payload.index(0, cursor)
        tag = payload[cursor:end_tag].decode('ascii')
        offset, length = struct.unpack_from('>ii', payload, end_tag + 1)
        cursor = end_tag + 9
        absolute = offset + 2
        if offset % 4 or length < 1 or absolute + length > len(payload):
            raise ValueError('Bad aligned import range')
        data = payload[absolute:absolute + length]
        if data[-1:] != b'\0':
            raise ValueError('Missing import padding byte')
        entries.append({'tag': tag, 'offset_without_flags': offset, 'stored_bytes': length,
                        'bytes': length - 1, 'sha256': sha(data[:-1]), 'data': data[:-1]})
    previous_end = cursor
    for entry in entries:
        start = entry['offset_without_flags'] + 2
        if start < previous_end or any(payload[previous_end:start]):
            raise ValueError('Overlapping imports or nonzero alignment padding')
        previous_end = start + entry['stored_bytes']
    if previous_end != len(payload):
        raise ValueError('Unaccounted payload bytes')
    return code, entries


def pack(source: Path, destination: Path, *, codec: str = 'UTF-8') -> dict:
    verify_host()
    result = subprocess.run([str(HOST), 'pack', str(source), str(destination), codec],
                            capture_output=True, text=True, timeout=10)
    if result.returncode:
        raise ValueError(result.stderr)
    report = json.loads(result.stdout)
    payload = destination.read_bytes()
    main, entries = unpack_table(payload)
    if main != base64.b64decode(report['main_base64']):
        raise ValueError('Native and independent main extraction disagree')
    if len(entries) != len(report['imports']):
        raise ValueError('Native and independent import counts disagree')
    for entry, native in zip(entries, report['imports']):
        if (entry['tag'], entry['data']) != (native['tag'], base64.b64decode(native['data_base64'])):
            raise ValueError('Native unpacker and firmware-layout decoder disagree')
    report['layout'] = [{k: value for k, value in item.items() if k != 'data'} for item in entries]
    report['format_overhead_bytes'] = len(payload) - len(main) - sum(item['bytes'] for item in entries)
    return report
