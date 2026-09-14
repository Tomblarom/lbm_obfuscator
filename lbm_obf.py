#!/usr/bin/env python3
"""Deterministic, token-preserving LispBM minimization. See README.md.

The Atom/List/Quote model continues this repository's original parser approach.
Historical Relys provenance and licensing are documented in NOTICE.md. No
allowlist, renaming, dead-code elimination or import-expression inlining is used.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
from typing import Iterator

VERSION = "2.1.0"
ENCODINGS = ("utf-8", "latin-1")
MAX_DEPTH = 128
MAX_FILES = 256
MAX_IMPORTS = 499  # Both CodeLoader::lispUnpackImports and firmware require < 500.
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
TOKEN_LIMIT = 256  # VESC 7.00 / LispBM 0.36.0 tokpar.h
WHITESPACE = " \t\r\n\v\f"
ESCAPES = dict(zip('0abtnvfres"\\d', '\0\a\b\t\n\v\f\r\x1b "\\\x7f'))
OPEN_CLOSE = {"(": ")", "{": "}", "[": "]", "[|": "|]"}
PREFIXES = {"'", "`", ",", ",@"}
FIXED = ("@const-start", "@const-end", "[|", "|]", ",@",
         "(", ")", "[", "]", "{", "}", ".", "_", "'", "`", ",", "?")
QUALIFIER = r"(f64|f32|i64|u64|i32|u32|i|u|b)?"
# tok_syntax precedes numbers, so a leading dot is a DOT, not a decimal.
FLOAT = re.compile(r"-?[0-9]*\.[0-9]+(?:e-?[0-9]+)?" + QUALIFIER, re.ASCII)
INTEGER = re.compile(r"-?(?:0[xX][0-9a-fA-F]+|[0-9]+)" + QUALIFIER, re.ASCII)
INVALID_HEX = re.compile(r"-?0[xX](?![0-9a-fA-F])", re.ASCII)
SYMBOL = re.compile(r"[a-zA-Z+*/=<>#!-][a-zA-Z0-9+*/=<>!?_-]*", re.ASCII)
WORD_KINDS = {"symbol", "number", "string", "char", "dot", "wildcard", "match"}
REFLECTION = {"eval", "eval-program", "read", "read-program", "read-eval-program",
              "str2sym", "sym2str", "sym2u", "u2sym", "set", "undefine"}


class MinimizeError(ValueError):
    """An input or output cannot be handled without an unsafe assumption."""


@dataclass(frozen=True)
class Token:
    kind: str
    text: str
    start: int
    end: int
    line: int
    column: int
    filename: str

    def error(self, message: str) -> MinimizeError:
        return MinimizeError(f"{self.filename}:{self.line}:{self.column}: {message}")


@dataclass(frozen=True)
class Atom:
    token: Token


@dataclass(frozen=True)
class List:
    opening: Token
    items: tuple[Node, ...]
    closing: Token


@dataclass(frozen=True)
class Quote:
    prefix: Token
    expr: Node


Node = Atom | List | Quote


def tokenize(source: str, filename: str = "<string>", *, encoding: str = "utf-8") -> list[Token]:
    """Scan every character; never skip an unrecognized reader construct.

    Token order and spellings follow the pinned LispBM tokenizer, including
    numeric suffixes, fixed-size reader tokens, ASCII case and byte characters.
    """
    if encoding not in ENCODINGS:
        raise MinimizeError(f"unsupported source encoding {encoding!r}; choose one of {ENCODINGS}")
    try:
        source.encode(encoding)
    except UnicodeEncodeError as exc:
        raise MinimizeError(f"{filename}: source cannot be represented as {encoding}: {exc}") from exc
    tokens: list[Token] = []
    pos, line, column = 0, 1, 1

    def token(kind: str, end: int) -> Token:
        return Token(kind, source[pos:end], pos, end, line, column, filename)

    def advance(end: int) -> None:
        nonlocal pos, line, column
        part = source[pos:end]
        lines = part.count("\n")
        line += lines
        column = len(part.rsplit("\n", 1)[-1]) + 1 if lines else column + len(part)
        pos = end

    if "\0" in source:
        end = source.index("\0")
        advance(end)
        raise token("invalid", end + 1).error("raw NUL byte is not supported; use a LispBM escape")
    if source.startswith("#!"):
        raise token("invalid", 2).error("shebang syntax depends on firmware build flags; remove it explicitly")
    while pos < len(source):
        char = source[pos]
        if char in WHITESPACE:
            advance(pos + 1)
            continue
        if char == ";":
            end = source.find("\n", pos)
            advance(len(source) if end < 0 else end)
            continue
        if char == '"':
            end, byte_length = pos + 1, 0
            while end < len(source) and source[end] != '"':
                if source[end] == "\\":
                    end += 1
                    if end == len(source) or source[end] not in ESCAPES:
                        raise token("string", end).error("invalid or incomplete LispBM string escape")
                    byte_length += 1
                else:
                    byte_length += len(source[end].encode(encoding))
                end += 1
            if end == len(source):
                raise token("string", end).error("unterminated string")
            if byte_length > TOKEN_LIMIT:
                raise token("string", end).error(f"string exceeds the {TOKEN_LIMIT}-byte LispBM reader limit")
            current = token("string", end + 1)
        elif source.startswith("\\#", pos):
            end = pos + 2
            if end == len(source):
                raise token("char", end).error("incomplete LispBM character literal")
            if source[end] == "\\":
                end += 1
                if end == len(source) or source[end] not in ESCAPES:
                    raise token("char", end).error("invalid or incomplete LispBM character escape")
            elif ord(source[end]) > 127:
                raise token("char", end + 1).error("character literals must contain a single ASCII byte")
            current = token("char", end + 1)
        else:
            fixed = next((text for text in FIXED if source.startswith(text, pos)), None)
            if fixed is not None:
                if fixed in OPEN_CLOSE:
                    kind = "open"
                elif fixed in OPEN_CLOSE.values():
                    kind = "close"
                elif fixed in PREFIXES:
                    kind = "prefix"
                elif fixed.startswith("@"):
                    kind = "directive"
                else:
                    kind = {".": "dot", "_": "wildcard", "?": "match"}[fixed]
                current = token(kind, pos + len(fixed))
            else:
                if INVALID_HEX.match(source, pos):
                    raise token("number", pos + 2).error("hexadecimal literal is missing its digits")
                match = FLOAT.match(source, pos) or INTEGER.match(source, pos)
                if match:
                    qualifier = match[1] or ""
                    floating = "." in match[0]
                    if (floating and qualifier not in {"", "f32", "f64"}
                            or not floating and qualifier in {"f32", "f64"}):
                        raise token("number", match.end()).error("numeric qualifier does not match literal kind; floats require a decimal point")
                    # tok_double's scratch buffer is 128 bytes. Refuse its
                    # overflow fallback rather than interpreting an approximation.
                    if "." in match[0] and len(match[0]) >= 128:
                        raise token("number", match.end()).error("floating literal exceeds supported reader length")
                    if "." in match[0] and source[match.end():match.end() + 1] == "e":
                        raise token("number", match.end()).error("malformed LispBM exponent (use e followed by optional minus and digits)")
                    current = token("number", match.end())
                else:
                    match = SYMBOL.match(source, pos)
                    if not match:
                        raise token("invalid", pos + 1).error(f"unsupported reader character {char!r}")
                    current = token("symbol", match.end())
                    if len(current.text) > TOKEN_LIMIT:
                        raise current.error(f"symbol exceeds the {TOKEN_LIMIT}-byte LispBM reader limit")
        tokens.append(current)
        advance(current.end)
    return tokens


def parse_tokens(tokens: list[Token]) -> tuple[Node, ...]:
    pos = 0

    def expression(depth: int) -> Node:
        nonlocal pos
        current = tokens[pos]
        if depth > MAX_DEPTH:
            raise current.error(f"nesting exceeds the supported depth of {MAX_DEPTH}")
        pos += 1
        if current.kind == "close":
            raise current.error(f"unexpected closing delimiter {current.text!r}")
        if current.kind == "prefix":
            if pos == len(tokens) or tokens[pos].kind in {"close", "directive"}:
                raise current.error("reader prefix is missing its expression")
            return Quote(current, expression(depth + 1))
        if current.kind == "directive" and depth:
            raise current.error("const directives are supported only between top-level forms")
        if current.kind != "open":
            if current.kind == "dot" and depth == 0:
                raise current.error("dot outside a list")
            return Atom(current)
        items: list[Node] = []
        expected = OPEN_CLOSE[current.text]
        while pos < len(tokens) and tokens[pos].kind != "close":
            items.append(expression(depth + 1))
        if pos == len(tokens):
            raise current.error(f"unclosed {current.text!r}; expected {expected!r}")
        closing = tokens[pos]
        if closing.text != expected:
            raise closing.error(f"mismatched delimiter; expected {expected!r} for {current.line}:{current.column}")
        pos += 1
        dots = [i for i, item in enumerate(items) if isinstance(item, Atom) and item.token.kind == "dot"]
        if dots and (current.text != "(" or len(dots) != 1 or dots[0] == 0 or dots[0] != len(items) - 2):
            raise current.error("malformed dotted list")
        if current.text == "[" and any(not isinstance(item, Atom) or item.token.kind not in {"number", "char"} for item in items):
            raise current.error("byte-buffer literals may contain only numeric or character literals")
        return List(current, tuple(items), closing)

    forms = []
    while pos < len(tokens):
        forms.append(expression(0))
    return tuple(forms)


def parse(source: str, filename: str = "<string>", *, encoding: str = "utf-8") -> tuple[Node, ...]:
    return parse_tokens(tokenize(source, filename, encoding=encoding))


def node_tokens(node: Node) -> Iterator[Token]:
    if isinstance(node, Atom):
        yield node.token
    elif isinstance(node, Quote):
        yield node.prefix
        yield from node_tokens(node.expr)
    else:
        yield node.opening
        for item in node.items:
            yield from node_tokens(item)
        yield node.closing


def head(node: Node) -> str | None:
    if isinstance(node, List) and node.opening.text == "(" and node.items:
        first = node.items[0]
        if isinstance(first, Atom) and first.token.kind == "symbol":
            return first.token.text.lower()
    return None


def executable_lists(node: Node) -> Iterator[List]:
    # Quotes/array literals are data, not VESC Tool directives. Quasiquotes
    # remain intact as well; this traversal never authorizes a transformation.
    if not isinstance(node, List) or node.opening.text in {"[", "[|"}:
        return
    yield node
    if head(node) != "quote":
        for item in node.items:
            yield from executable_lists(item)


def emit(forms: tuple[Node, ...], *, encoding: str = "utf-8") -> str:
    pieces: list[str] = []
    previous: Token | None = None
    expected: list[tuple[str, str]] = []
    for form in forms:
        own_line = head(form) == "import" or isinstance(form, Atom) and form.token.kind == "directive"
        if own_line and pieces and not pieces[-1].endswith("\n"):
            pieces.append("\n")
            previous = None
        for token in node_tokens(form):
            if previous and (previous.kind in WORD_KINDS and token.kind in WORD_KINDS
                             or head(form) == "import" and previous.kind == "string" and token.kind == "prefix"):
                pieces.append(" ")
            pieces.append(token.text)
            expected.append((token.kind, token.text))
            previous = token
        if own_line:
            pieces.append("\n")
            previous = None
    text = "".join(pieces)
    if text.startswith("#!"):
        text = "\n" + text  # Do not create a shebang by removing leading comments.
    if text and not text.endswith("\n"):
        text += "\n"
    actual = [(t.kind, t.text) for t in tokenize(text, "<generated>", encoding=encoding)]
    if actual != expected:
        raise MinimizeError("internal error: emission changed token boundaries; no output written")
    return text


def minimize_source(source: str, filename: str = "<string>", *, encoding: str = "utf-8") -> str:
    """Compact source without I/O. Use compile_file to resolve/validate imports."""
    return emit(parse(source, filename, encoding=encoding), encoding=encoding)


def decode_string(token: Token) -> str:
    text, result, pos = token.text[1:-1], [], 0
    while pos < len(text):
        if text[pos] == "\\":
            pos += 1
            result.append(ESCAPES[text[pos]])
        else:
            result.append(text[pos])
        pos += 1
    return "".join(result)


def path_literal(path: str, token: Token, *, encoding: str = "utf-8") -> Token:
    # VESC Tool has a line-based import preprocessor, not LispBM's string reader.
    if any(c in path for c in ('"', "\\", "\n", "\r", "\0")):
        raise token.error("import paths containing quotes, backslashes or control line breaks are unsupported")
    result = replace(token, text='"' + path + '"')
    tokenize(result.text, token.filename, encoding=encoding)  # Includes the reader string-size limit.
    return result


def vesc_import_lines(source: str) -> dict[int, tuple[str, str]]:
    """The *textual* CodeLoader::getImportFromLine contract, dc53c658.

    This is only a compatibility guard. Native Qt pack/unpack tests check it
    against the pinned VESC Tool function. In particular, Qt's routine does
    not track strings, quotes, tab indentation or quoted trailing comments.
    """
    result = {}
    for number, raw in enumerate(source.split("\n"), 1):
        line = raw.lstrip(" ")
        while line.startswith("( "):
            line = line[0] + line[2:]
        if not line.lower().startswith("(import "):
            continue
        start, end = line.find('"'), line.rfind('"')
        path = tag = ""
        if start > 0 and end > start:
            path = line[start + 1:end]
            tag = line[end + 1:]
            for character in ("\r", " ", ")", "'"):
                tag = tag.replace(character, "")
            tag = tag.split(";", 1)[0]
        result[number] = (path, tag)
    return result


def validate_vesc_imports(source: str, forms: tuple[Node, ...], filename: str) -> None:
    expected = {}
    for form in forms:
        if head(form) == "import":
            # Input syntax has already been checked by imports_in; generated
            # syntax uses the same literal structure and is parsed afresh.
            name, binding = form.items[1:]
            expected[form.opening.line] = (decode_string(name.token), binding.expr.token.text)
    actual = vesc_import_lines(source)
    for number in sorted(set(expected) | set(actual)):
        if actual.get(number) != expected.get(number):
            raise MinimizeError(
                f"{filename}:{number}:1: VESC Tool import recognition differs from LispBM structure; "
                "use standalone declarations with spaces, no quoted trailing comments, "
                "and no import-looking lines inside quoted data or multiline strings"
            )


@dataclass(frozen=True)
class Import:
    form: List
    owner: Path
    path: Path
    binding: str
    path_token: Token


@dataclass
class SourceFile:
    path: Path
    data: bytes
    forms: tuple[Node, ...]
    imports: tuple[Import, ...]


def imports_in(forms: tuple[Node, ...], owner: Path, *, encoding: str = "utf-8") -> tuple[Import, ...]:
    imports = []
    for form in forms:
        for call in executable_lists(form):
            if head(call) != "import":
                continue
            if call is not form:
                raise call.opening.error("import must be a literal top-level VESC Tool declaration")
            if call.items[0].token.text != "import":
                raise call.opening.error("VESC Tool import declarations must use lowercase 'import'")
            import_line = call.opening.line
            if call.closing.line != import_line or any(
                    token.line <= import_line <= token.line + token.text.count("\n")
                    for other in forms if other is not form for token in node_tokens(other)):
                raise call.opening.error("VESC Tool import declarations must occupy their own source line")
            if len(call.items) != 3:
                raise call.opening.error("expected (import \"local-file\" 'binding)")
            name, binding = call.items[1:]
            if not isinstance(name, Atom) or name.token.kind != "string" or not isinstance(binding, Quote) or binding.prefix.text != "'" or not isinstance(binding.expr, Atom) or binding.expr.token.kind != "symbol":
                raise call.opening.error("expected a literal import path and a quoted symbol binding")
            value = decode_string(name.token)
            if "\\" in name.token.text:
                raise name.token.error("escaped import paths are not supported by the VESC Tool contract")
            if not value or (value.startswith("pkg") and "@" in value) or "://" in value:
                raise name.token.error("only explicit local import files are supported; resolve package/URL imports first")
            path_literal(value, name.token, encoding=encoding)
            path = Path(value)
            try:
                path = (path if path.is_absolute() else owner.parent / path).resolve(strict=True)
            except (OSError, RuntimeError) as exc:
                raise name.token.error(f"cannot resolve import {value!r}: {exc}") from exc
            imports.append(Import(call, owner, path, binding.expr.token.text.lower(), name.token))
    return tuple(imports)


def read_input(path: Path) -> bytes:
    try:
        info = path.stat()
        if not stat.S_ISREG(info.st_mode):
            raise MinimizeError(f"{path}: input must be a regular file")
        if info.st_size > MAX_FILE_BYTES:
            raise MinimizeError(f"{path}: input exceeds the {MAX_FILE_BYTES}-byte limit")
        return path.read_bytes()
    except OSError as exc:
        raise MinimizeError(f"{path}: cannot read input: {exc}") from exc


def load_graph(root: Path, *, encoding: str = "utf-8") -> dict[Path, SourceFile]:
    files: dict[Path, SourceFile] = {}
    active: list[Path] = []
    total = 0

    def visit(path: Path, as_code: bool) -> None:
        nonlocal total
        if path in active:
            chain = " -> ".join(str(p) for p in active + [path])
            raise MinimizeError(f"import cycle: {chain}")
        if path in files:
            return
        if len(active) >= MAX_DEPTH or len(files) >= MAX_FILES:
            raise MinimizeError("import graph exceeds the supported depth/file count")
        data = read_input(path)
        total += len(data)
        if total > MAX_TOTAL_BYTES:
            raise MinimizeError("import graph exceeds the supported total byte count")
        forms: tuple[Node, ...] = ()
        if as_code:
            try:
                text = data.decode(encoding)
            except UnicodeDecodeError as exc:
                raise MinimizeError(f"{path}: cannot decode LispBM source as {encoding}: {exc}; "
                                    "select another encoding only for a known byte encoding") from exc
            forms = parse(text, str(path), encoding=encoding)
        imports = imports_in(forms, path, encoding=encoding)
        if path == root:
            validate_vesc_imports(text, forms, str(path))
            if len(imports) > MAX_IMPORTS:
                raise imports[MAX_IMPORTS].path_token.error(
                    f"VESC Tool/firmware support at most {MAX_IMPORTS} import declarations, including repeats")
        files[path] = SourceFile(path, data, forms, imports)
        active.append(path)
        for item in imports:
            visit(item.path, item.path.suffix.lower() in {".lisp", ".lbm"})
        active.pop()

    visit(root, True)
    for path, source in files.items():
        if path != root and source.imports:
            raise source.imports[0].path_token.error(
                "nested import declarations are not processed by LispBM read-eval-program; "
                "declare dependencies in the root source (no output written)"
            )
    bindings: dict[str, Path] = {}
    for item in files[root].imports:
        if item.binding in bindings and bindings[item.binding] != item.path:
            raise item.path_token.error(f"conflicting import binding {item.binding!r}")
        bindings[item.binding] = item.path
    return files


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass
class Build:
    output: Path
    report_path: Path
    code: str
    report: dict
    artifacts: dict[Path, bytes]
    inputs: tuple[Path, ...]


def compile_file(input_path: Path | str, output: Path | str | None = None,
                 report_path: Path | str | None = None, *, bundle: bool = False,
                 encoding: str = "utf-8") -> Build:
    """Prepare and validate a complete build in memory; never write inputs."""
    if encoding not in ENCODINGS:
        raise MinimizeError(f"unsupported source encoding {encoding!r}; choose one of {ENCODINGS}")
    try:
        root = Path(input_path).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise MinimizeError(f"cannot resolve input {input_path}: {exc}") from exc
    output = Path(output).absolute() if output is not None else root.with_name(root.stem + "_min" + (root.suffix or ".lbm"))
    report_path = Path(report_path).absolute() if report_path is not None else output.with_name(output.name + ".json")
    files = load_graph(root, encoding=encoding)
    source = files[root]
    artifacts: dict[Path, bytes] = {}
    replacements: dict[int, List] = {}
    import_records = []
    for item in source.imports:
        data = files[item.path].data
        destination = item.path
        if bundle:
            destination = output.parent / (output.name + ".imports") / (sha256(data) + item.path.suffix)
            artifacts[destination] = data
        relative = os.path.relpath(destination, output.parent)
        filename = Atom(path_literal(Path(relative).as_posix(), item.path_token, encoding=encoding))
        # Canonical, standalone import lines accepted by the VESC Tool preprocessor.
        new_form = replace(item.form, items=(item.form.items[0], filename, item.form.items[2]))
        replacements[id(item.form)] = new_form
        import_records.append({"binding": item.binding, "source": str(item.path),
                               "output_path": relative, "bytes": len(data), "sha256": sha256(data),
                               "policy": "byte-for-byte"})
    forms = tuple(replacements.get(id(form), form) for form in source.forms)
    code = emit(forms, encoding=encoding)
    validate_vesc_imports(code, parse(code, "<generated>", encoding=encoding), "<generated>")
    output_data = code.encode(encoding)
    tokens = [token for file in files.values() for form in file.forms for token in node_tokens(form)]
    counts = Counter(t.text for t in tokens if t.kind == "symbol")
    spellings: dict[str, list[str]] = defaultdict(list)
    for name in sorted(counts):
        spellings[name.lower()].append(name)
    dependencies = sum(record["bytes"] for record in import_records)
    resolved_size = len(source.data) + dependencies
    output_size = len(output_data) + dependencies
    diagnostics = [{"code": "symbols-preserved", "message": "All symbols, bindings, quoted data, firmware APIs and thread strings are preserved; no renaming or expression removal."}]
    for token in tokens:
        if token.kind == "symbol" and token.text.lower() in REFLECTION:
            diagnostics.append({"code": "reflective-symbol-use-preserved", "symbol": token.text,
                                "file": token.filename, "line": token.line, "column": token.column})
    if import_records:
        diagnostics.append({"code": "import-bytes-preserved", "message": "Import bytearrays and separate reader states are retained. Payload sizes include each import declaration; table/alignment/NUL overhead is excluded."})
    for file in files.values():
        directives = [t.text for form in file.forms for t in node_tokens(form) if t.kind == "directive"]
        if directives and directives[-1] == "@const-start":
            diagnostics.append({"code": "open-const-region", "file": str(file.path),
                                "message": "Const mode remains active at end of this reader channel, as in the input."})
    report = {
        "schema_version": 1, "tool_version": VERSION,
        "source_encoding": encoding, "output_encoding": encoding, "report_encoding": "utf-8",
        "input": str(root), "output": str(output), "mode": "bundle" if bundle else "references",
        "source_sha256": sha256(source.data), "output_sha256": sha256(output_data),
        "inputs": [{"path": str(file.path), "bytes": len(file.data), "sha256": sha256(file.data)}
                   for file in files.values()],
        "sizes": {"source_bytes": len(source.data), "import_bytes": dependencies,
                  "resolved_payload_bytes": resolved_size, "output_source_bytes": len(output_data),
                  "output_payload_bytes": output_size, "saved_bytes": resolved_size - output_size,
                  "saved_percent": round(100 * (resolved_size - output_size) / resolved_size, 2) if resolved_size else 0.0},
        "symbol_mapping": {name: name for name in sorted(counts)},
        "symbols": [{"canonical": name, "spellings": spellings[name],
                     "occurrences": sum(counts[s] for s in spellings[name])} for name in sorted(spellings)],
        "imports": import_records, "diagnostics": diagnostics,
    }
    if output in artifacts or report_path in artifacts or report_path == output:
        raise MinimizeError("output, report and bundle file destinations must be distinct")
    artifacts[output] = output_data
    artifacts[report_path] = (json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    build = Build(output, report_path, code, report, artifacts, tuple(files))
    validate_outputs(build)
    return build


def validate_outputs(build: Build) -> None:
    destinations: set[Path] = set()
    for target in build.artifacts:
        try:
            resolved = target.resolve()
            for source in build.inputs:
                if resolved == source or target.exists() and os.path.samefile(target, source):
                    raise MinimizeError(f"refusing to overwrite input/dependency: {target}")
            if resolved in destinations:
                raise MinimizeError(f"output destinations alias each other: {target}")
            destinations.add(resolved)
            if target.exists() or target.is_symlink():
                raise MinimizeError(f"output already exists (never overwritten): {target}")
            for parent in target.parents:
                if parent.exists() and not parent.is_dir():
                    raise MinimizeError(f"output parent is not a directory: {parent}")
        except (OSError, RuntimeError) as exc:
            raise MinimizeError(f"cannot validate output {target}: {exc}") from exc
    if any(parent.resolve() in destinations for target in build.artifacts for parent in target.parents):
        raise MinimizeError("a planned output file is another output's parent directory")


def write_build(build: Build) -> None:
    """Stage everything, then create destinations atomically without replacement."""
    validate_outputs(build)
    staged: dict[Path, Path] = {}
    published: list[Path] = []
    try:
        for target, data in build.artifacts.items():
            target.parent.mkdir(parents=True, exist_ok=True)
            fd, name = tempfile.mkstemp(prefix=".lbm-min-", dir=target.parent)
            staged[target] = Path(name)
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
        for target, temp in staged.items():
            os.link(temp, target)  # O_EXCL-like publication; never replaces a symlink or hardlink.
            published.append(target)
    except OSError as exc:
        for target in published:
            if target.exists() and os.path.samefile(target, staged[target]):
                target.unlink()
        raise MinimizeError(f"cannot publish output: {exc}") from exc
    finally:
        for temp in staged.values():
            temp.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="LispBM source (.lisp or .lbm; default UTF-8)")
    parser.add_argument("-o", "--output", type=Path, help="new output file (default: INPUT_min.EXT)")
    parser.add_argument("--report", type=Path, help="new JSON report (default: OUTPUT.json)")
    parser.add_argument("--bundle", action="store_true", help="copy local imports byte-for-byte beside the output")
    parser.add_argument("--encoding", choices=ENCODINGS, default="utf-8",
                        help="explicit source/output byte encoding; never guessed (default: utf-8)")
    parser.add_argument("--obfuscate", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--version", action="version", version=VERSION)
    args = parser.parse_args(argv)
    if args.obfuscate:
        parser.error("unsafe legacy symbol/thread obfuscation has been removed; use deterministic minimization")
    try:
        build = compile_file(args.input, args.output, args.report, bundle=args.bundle, encoding=args.encoding)
        write_build(build)
    except MinimizeError as exc:
        print(f"lbm_obf: error: {exc}", file=sys.stderr)
        return 2
    sizes = build.report["sizes"]
    print(f"Source: {sizes['source_bytes']} bytes; resolved payload: {sizes['resolved_payload_bytes']} bytes")
    print(f"Output source: {sizes['output_source_bytes']} bytes; output payload: {sizes['output_payload_bytes']} bytes")
    print(f"Saved: {sizes['saved_bytes']} bytes ({sizes['saved_percent']:.2f}%)")
    print(f"Output: {build.output}\nReport: {build.report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
