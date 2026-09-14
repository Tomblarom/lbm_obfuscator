#!/usr/bin/env python3
"""Export a reference symbol list from local Markdown documentation to stdout.

The minimizer preserves all symbols. The old network-updated renaming allowlist and
source rewriting are retired. This helper is read-only and is useful only for
reference inventories; its output never authorizes a symbol transformation.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

HEADING = re.compile(r'^#{3,4}\s+`?([a-zA-Z+*/=<>!?_-][a-zA-Z0-9+*/=<>!?_-]*)`?(?:\s|$)')


def extract_h4_symbols(markdown: str) -> list[str]:
    """Keep the historical helper name; core APIs use ### as well as ####."""
    return sorted({match[1].lower() for line in markdown.splitlines()
                   if (match := HEADING.match(line))})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('references', nargs='+', type=Path, help='local LispBM/VESC documentation files')
    args = parser.parse_args()
    symbols = set()
    for reference in args.references:
        try:
            symbols.update(extract_h4_symbols(reference.read_text(encoding='utf-8')))
        except (OSError, UnicodeError) as exc:
            parser.error(f'{reference}: {exc}')
    print(json.dumps(sorted(symbols), indent=2))


if __name__ == '__main__':
    main()
