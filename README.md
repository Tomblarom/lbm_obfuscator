# lbm_obfuscator

`lbm_obf.py` compacts LispBM source deterministically. It removes comments and
unnecessary token whitespace, preserving strings, character literals, numeric
types, symbols, quoted data, bindings, firmware APIs and functional expressions.
Python 3.10 or newer is sufficient for the tool; there are no Python packages
to install.

## Usage

```sh
python3 lbm_obf.py path/to/main.lisp
python3 lbm_obf.py path/to/main.lbm -o build/main_min.lbm --bundle
```

The first command creates `main_min.lisp` and `main_min.lisp.json` beside the
input. A `.lbm` input similarly produces `main_min.lbm`. `--output` (`-o`) and
`--report` select explicit destinations.

**Existing files are never replaced.** Source files, imports, symlink/hardlink
aliases, earlier outputs and reports are protected. Choose a new destination
for a new build. Validation precedes publication; outputs are staged and
created without replacement.

UTF-8 is decoded strictly by default. For a known single-byte source, select
`--encoding latin-1` explicitly. Source and output use the same byte encoding;
string bytes remain intact and JSON reports always use UTF-8. There is no
encoding detection or replacement decoding.

## Behavior

- Comments and unnecessary token whitespace are removed.
- Strings, characters, quoted data, numeric spellings and types are retained.
- All symbols are preserved, including unknown firmware extensions and `main`.
- `print`, `puts`, diagnostic expressions, threads and argument side effects
  remain in the program.
- Local imports are validated, rebased to the output location and optionally
  copied into a portable bundle.
- A JSON report contains byte sizes, source/output hashes, imports, an identity
  symbol mapping and diagnostics.

LispBM symbols can be data and can be obtained through `str2sym` or `read`.
Closures and macros are also inspectable. This version therefore does not
shorten symbol names or rewrite thread-name strings. The former random
obfuscation is unavailable; `--obfuscate` returns a migration message.

No firmware-name allowlist is required. The optional documentation helper
exports an inventory from local Markdown files without modifying source:

```sh
python3 update_preserved_names.py path/to/lispbm-reference.md
```

## Imports

Use a literal declaration on its own source line:

```clj
(import "modules/display.lisp" 'code-disp)
(print "this expression is retained")
(read-eval-program code-disp)
```

VESC imports bind bytearrays before execution. Their contents and bindings
remain observable, and `read-eval-program` has a separate reader state.
The minimizer retains the imported bytes and evaluation calls.

- Relative paths are resolved against the source file's directory. Direct
  imports from subdirectories and absolute local paths are supported.
- Normal output references the original imports using paths relative to the
  output directory.
- `--bundle` copies dependencies byte for byte into `OUTPUT.imports/`, using
  content-hash filenames. Keep this directory with the main file. Binary
  imports are supported.
- Repeated declarations and evaluation calls keep their order and multiplicity.
  Conflicting files bound to the same symbol fail.
- Missing files, cycles and unsupported declarations fail before output is
  written. The import table permits at most 499 declarations, including repeats.

The supported declaration layout uses lowercase `import`, spaces, a literal
path and a quoted symbol. Escaped paths, embedded quotes/line breaks, and
layouts recognized differently by VESC Tool are rejected. This includes tab
indentation/separation, quoted trailing comments and import-looking physical
lines inside quoted data or multiline strings.

Package/URL imports must first be supplied as explicit local files. A Lisp
dependency containing its own import declarations is rejected: runtime reading
of an imported bytearray does not recursively package those dependencies.

See [VESC payload compatibility](docs/vesc-payload.md) for native packing tests,
the binary format and the encoding boundary in VESC Tool.

## Reports

The CLI prints size totals and writes JSON, by default to `OUTPUT.json`:

| Field | Meaning |
| --- | --- |
| `source_bytes` | Original main source in its declared encoding |
| `import_bytes` | Imported bytes, counted per declaration |
| `resolved_payload_bytes` | Original main source plus imports |
| `output_source_bytes` | Minimized main source |
| `output_payload_bytes` | Minimized main source plus unchanged imports |
| `saved_bytes`, `saved_percent` | Reduction of the source payload |

Hashes, source/output encodings, symbol spellings, occurrences, reflective
symbol sites and open const regions support inspection of the result. Empty
inputs receive a valid zero-size report.

Source-size totals exclude container tables, NUL padding and alignment. They
do not measure firmware flash capacity or updater reserve.

## Supported syntax and limits

The scanner is checked against LispBM 0.36.0, vendored by VESC 7.00 at
`20cbb362687291242ab90b99f25fbfe8835540fc`. It handles ASCII symbols,
hexadecimal and typed numbers, decimal exponents, `\#` characters, LispBM
string escapes, dotted lists, `[]`, `[| |]`, `{}`, quote, quasiquote,
unquote/splice and top-level `@const-start` / `@const-end`.

Malformed syntax and unsupported reader characters fail with a location.
Raw NUL bytes and firmware-dependent shebang syntax are rejected. Floats need
a decimal point and an optional `f32`/`f64` suffix; integer suffixes are `b`,
`i`, `u`, `i32`, `u32`, `i64`, `u64`. Tokens are not interpreted as Common Lisp
or Scheme, and emitted token boundaries are checked again.

Limits: 256 bytes per decoded string/symbol, floating tokens shorter than 128
characters, nesting depth 128, files up to 16 MiB, and a graph of up to 256
files / 64 MiB. An open const region at EOF is preserved and reported.

Unknown function calls are preserved. The tool does not validate firmware API
availability or repair input programs. Equality tests use stated inputs;
runtime timing, memory budgets, error line numbers and inspection of the main
source's bytes are outside that contract.

## Development and tests

```sh
# Python regression and input-protection checks
python3 -m unittest tests.test_minimizer tests.test_import_compatibility -v

# Build the pinned real 32-bit LispBM evaluator
python3 tools/bootstrap_lispbm.py

# Debian x86_64 without installed multilib development files:
python3 tools/bootstrap_lispbm.py --local-debian-sysroot

# Optional native VESC Tool payload checks (requires Qt 5 Core and qmake)
python3 tools/bootstrap_vesc_payload.py

python3 -m unittest discover -s tests -v
```

Both bootstraps verify pinned source hashes and build with one compiler job.
Use `--offline` to require already cached sources. Downloads, temporary files,
builds and traces stay under ignored `.cache/`; nothing is installed globally.
The test suite uses self-contained fixtures and public upstream syntax tests.
Actual LispBM execution compares original and minimized results; Python checks
alone are not treated as equivalence evidence.

See [testing](docs/testing.md) for prerequisites and coverage, and
[NOTICE.md](NOTICE.md) for licensing and source provenance.
