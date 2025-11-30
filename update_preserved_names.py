#!/usr/bin/env python3
# pulls only '#### <name of function>' headings from the given Markdown refs and adds them to imported_names of lbm_obf.py

import sys, re, ast, pathlib, datetime as dt
from urllib.request import urlopen

URLS = [
    'https://raw.githubusercontent.com/svenssonjoel/lispBM/refs/heads/master/doc/lbmref.md',
    'https://raw.githubusercontent.com/vedderb/bldc/refs/heads/master/lispBM/README.md',
]

H4_RE = re.compile(r'^####\s+(.+?)\s*$')  # capture text after '#### '
SYMBOL_CLEAN_RE = re.compile(r'^`?([a-zA-Z+\-/*<>=!?_][a-zA-Z0-9+\-/*<>=!?_]*)`?$')

def fetch(url: str) -> str:
    with urlopen(url) as r:
        enc = r.headers.get_content_charset() or 'utf-8'
        return r.read().decode(enc, 'replace')

def extract_h4_symbols(md: str):
    out = []
    for line in md.splitlines():
        m = H4_RE.match(line)
        if not m:
            continue
        raw = m.group(1).strip()
        # Common patterns: 'print', '`print`', '+', '`<=`', sometimes text after name like 'print – Print string'
        first = raw.split()[0]
        m2 = SYMBOL_CLEAN_RE.match(first)
        if m2:
            out.append(m2.group(1))
        # also allow raw operators that may not match SYMBOL_CLEAN_RE (e.g. '==', though rare)
        elif first in {'+', '-', '*', '/', '//', '<', '>', '<=', '>=', '='}:
            out.append(first)
    # keep order and dedupe
    seen, ordered = set(), []
    for s in out:
        if s not in seen:
            ordered.append(s); seen.add(s)
    return ordered

def load_name_list(py_path: pathlib.Path, var_name: str):
    src = py_path.read_text(encoding='utf-8')
    tree = ast.parse(src, filename=str(py_path))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == var_name:
                    if isinstance(node.value, (ast.List, ast.Tuple)):
                        vals = []
                        for elt in node.value.elts:
                            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                vals.append(elt.value)
                            else:
                                raise RuntimeError(f'{var_name} must be a list of string literals.')
                        return vals, src
    raise RuntimeError(f"Could not find top-level '{var_name} = [...]'")

def append_name_list(py_path: pathlib.Path, original_src: str, var_name: str, existing_entries, new_entries):
    if not new_entries:
        return

    combined_entries = existing_entries + new_entries
    lines = original_src.splitlines(keepends=True)
    start_idx = end_idx = None
    var_re = re.compile(rf'(\s*){var_name}\s*=\s*\[')

    for idx, line in enumerate(lines):
        if start_idx is None:
            if var_re.match(line):
                start_idx = idx
                if ']' in line[line.find('['):]:
                    end_idx = idx
                    break
        else:
            if line.strip().startswith(']'):
                end_idx = idx
                break

    if start_idx is None or end_idx is None:
        raise RuntimeError(f"Could not locate {var_name} list boundaries.")

    newline = '\r\n' if '\r\n' in original_src else '\n'
    indent = var_re.match(lines[start_idx]).group(1)
    joined = ', '.join(repr(name) for name in combined_entries)
    block_line = f"{indent}{var_name} = [{joined}]{newline}"

    lines[start_idx:end_idx + 1] = [block_line]
    py_path.write_text(''.join(lines), encoding='utf-8')

def main():
    py_path = pathlib.Path('lbm_obf.py')
    preserved, _ = load_name_list(py_path, 'preserved_names')
    imported, src = load_name_list(py_path, 'imported_names')
    existing_lower = {name.lower() for name in preserved + imported}

    discovered = []
    for u in URLS:
        try:
            discovered.extend(sym.lower() for sym in extract_h4_symbols(fetch(u)))
        except Exception as e:
            print(f'[WARN] fetch failed {u}: {e}', file=sys.stderr)

    # missing = in doc order, no sorting
    missing, seen_new = [], set()
    for sym in discovered:
        if sym in existing_lower or sym in seen_new:
            continue
        missing.append(sym)
        seen_new.add(sym)

    if not missing:
        print('No new names found. imported_names unchanged.')
        return

    append_name_list(py_path, src, 'imported_names', imported, missing)
    print(f'Added {len(missing)} names to imported_names. New combined total: {len(preserved) + len(imported) + len(missing)}')

if __name__ == '__main__':
    main()
