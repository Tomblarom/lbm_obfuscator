#!/usr/bin/env python3
"""Build the pinned real LispBM test host locally, without system installation.

Normal Linux: python3 tools/bootstrap_lispbm.py
Debian x86_64 without multilib: add --local-debian-sysroot
Add --offline to require existing, verified source archives.
Downloads, temporary files and the single compiler job stay in .cache/.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".cache"
LOCK = json.loads((ROOT / "tools/lispbm-lock.json").read_text())


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cached_download(record: dict, directory: Path, *, offline: bool = False) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / record["name"]
    if not path.exists():
        if offline:
            raise RuntimeError(f"Source archive missing in offline mode: {path}")
        print(f"Downloading {record['name']}", flush=True)
        temp = path.with_suffix(path.suffix + ".download")
        try:
            with urlopen(record["url"], timeout=45) as source, temp.open("wb") as target:
                while block := source.read(1024 * 1024):
                    target.write(block)
            if digest(temp) != record["sha256"]:
                raise RuntimeError(f"SHA-256 mismatch for {record['name']}")
            temp.replace(path)
        finally:
            temp.unlink(missing_ok=True)
    if digest(path) != record["sha256"]:
        raise RuntimeError(f"SHA-256 mismatch for cached {record['name']}")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local-debian-sysroot", action="store_true")
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    sources, build, temporary = (CACHE / name for name in ("sources", "build", "tmp"))
    for directory in (sources, build, temporary):
        directory.mkdir(parents=True, exist_ok=True)
    archive = cached_download(LOCK["archive"], sources, offline=args.offline)
    lbm = sources / "lispbm"
    prefix = f"bldc-{LOCK['firmware_commit']}/lispBM/lispBM/"
    # Always verify/extract the source from the pinned archive, never silently
    # compile a modified cache. Only regular files below this prefix are used.
    with tarfile.open(archive) as tar:
        for member in tar:
            if member.isfile() and member.name.startswith(prefix):
                target = lbm / member.name[len(prefix):]
                if not target.resolve().is_relative_to(lbm.resolve()):
                    raise RuntimeError("unsafe source archive path")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(tar.extractfile(member).read())
    flags = ["-m32", "-static", "-O2", "-g", "-std=c11", "-Wall", "-Wextra",
             "-DFULL_RTS_LIB", "-DLBM_USE_DYN_FUNS", "-DLBM_USE_DYN_MACROS",
             "-DLBM_USE_DYN_LOOPS", "-DLBM_USE_DYN_ARRAYS", "-DLBM_USE_DYN_DEFSTRUCT",
             "-DLBM_USE_MACRO_REST_ARGS", "-DLBM_USE_ERROR_LINENO"]
    if args.local_debian_sysroot:
        sysroot = build / "sysroot"
        sysroot.mkdir(exist_ok=True)
        for record in LOCK["debian_sysroot"]:
            deb = cached_download(record, sources / "debs", offline=args.offline)
            subprocess.run(["dpkg-deb", "-x", str(deb), str(sysroot)], check=True)
        flags += [f"--sysroot={sysroot}", f"-B{sysroot}/usr/lib/gcc/x86_64-linux-gnu/14/32/",
                  f"-L{sysroot}/usr/lib32", "-isystem", str(sysroot / "usr/include/x86_64-linux-gnu")]
    core = ["env", "fundamental", "heap", "lbm_memory", "print", "stack", "symrepr", "tokpar",
            "extensions", "lispbm", "eval_cps", "lbm_c_interop", "lbm_custom_type", "lbm_channel",
            "lbm_flat_value", "lbm_prof", "lbm_defrag_mem", "lbm_image", "buffer"]
    extensions = ["array_extensions", "string_extensions", "math_extensions", "runtime_extensions",
                  "mutex_extensions", "lbm_dyn_lib"]
    c_files = [lbm / "src" / (name + ".c") for name in core]
    c_files += [lbm / "src/extensions" / (name + ".c") for name in extensions]
    c_files += [lbm / "platform/linux/src/platform_mutex.c", ROOT / "tests/lispbm_host.c"]
    executable = build / "lispbm-host"
    command = ["gcc", *flags, *map(str, c_files), "-o", str(executable),
               f"-I{lbm}/include", f"-I{lbm}/include/extensions", f"-I{lbm}/src",
               f"-I{lbm}/platform/linux/include", "-lpthread", "-lm"]
    print("Building pinned 32-bit LispBM 0.36.0 (one compiler job)", flush=True)
    subprocess.run(command, cwd=ROOT, env={**os.environ, "TMPDIR": str(temporary)}, check=True)
    manifest = {"firmware_commit": LOCK["firmware_commit"], "lispbm_tree": LOCK["lispbm_tree"],
                "word_bits": 32, "binary_sha256": digest(executable), "command": command,
                "host_sha256": digest(ROOT / "tests/lispbm_host.c"),
                "compiler": subprocess.check_output(["gcc", "--version"], text=True).splitlines()[0]}
    (build / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(executable)


if __name__ == "__main__":
    main()
