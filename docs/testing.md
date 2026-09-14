# Testing the minimizer

The tests cover scanner boundaries, malformed input, deterministic emission,
encodings, import resolution, safe output publication and actual LispBM
execution. They use self-contained source fixtures and pinned public upstream
sources.

## Python checks

Python 3.10 or newer is required; no third-party Python packages are needed.

```sh
python3 -m unittest tests.test_minimizer tests.test_import_compatibility -v
```

These checks include source/dependency aliases, symlinks and hardlinks,
existing outputs, write failures, cycles, missing files, import limits and
VESC Tool's textual import rules. Temporary files remain in `.cache/tmp/`.

## Native LispBM equivalence

The test host links the unmodified LispBM evaluator, reader and standard
extensions from the source pinned in `tools/lispbm-lock.json`. It supplies
constant import arrays, an emulated constant heap, assertions and output
traces. Firmware-specific calls in fixtures have controlled local substitutes.

On Linux with GCC and 32-bit development libraries:

```sh
python3 tools/bootstrap_lispbm.py
python3 -m unittest tests.test_lispbm -v
```

On Debian x86_64 without multilib development packages, the bootstrap can
download and unpack the pinned libraries into its local sysroot:

```sh
python3 tools/bootstrap_lispbm.py --local-debian-sysroot
```

This does not install system packages. To reuse only cached sources and
packages, add `--offline`. All build inputs are hash-checked. A single compiler
job runs, with temporary files below `.cache/`.

Original and minimized programs run in separate instances with equal inputs.
Native assertions and traces cover string/character bytes, numeric types,
quoting, recursive and local bindings, reflection, arrays, const directives,
side effects and firmware extension names. Separate cases check Latin-1
strings, CRLF, repeated imports and separate reader states. The default
integer-overflow assertion checks the 32-bit evaluator's 28-bit integer type.

Another check compares native reader values for a selected upstream syntax
corpus. Unsupported syntax is reported explicitly. Python does not simulate
the evaluated LispBM logic.

`LISPBM_HOST` can select an existing compatible test host. Linux sandboxes
that terminate 32-bit syscalls with `SIGSYS` require running this test binary
outside that syscall filter. The host contains no controller transport.

## Native VESC Tool payload tests

With Qt 5 Core development files, `qmake` and a C++ compiler installed:

```sh
python3 tools/bootstrap_vesc_payload.py
python3 -m unittest tests.test_vesc_payload -v
```

The bootstrap reads the exact public source files named in
`tools/vesc-tool-lock.json`. Use `--offline` for verified cached files or
`--source-repo /path/to/vesc_tool` to read that revision from an existing
local Git checkout. The checkout is not modified and lazy fetching is disabled.

The test driver compiles the original packing, unpacking and import-line
functions with QtCore and runs without controller access. A seccomp filter
blocks networking during driver execution. Tests compare binary and source
imports, table alignment, NUL padding, declared counts and encoding behavior.
See [payload compatibility](vesc-payload.md).

These optional tests visibly skip if their native driver has not been built.
The LispBM equivalence tests fail if their required host is missing.

## Full suite and artifacts

```sh
python3 -m unittest discover -s tests -v
```

Build manifests record compiler commands, versions and hashes. Native traces
are written below `.cache/results/equivalence/`; payload-test artifacts use
temporary cache directories. Generated files are not repository inputs.

Passing these tests establishes behavior for the exercised inputs. It does
not certify hardware timing, firmware API availability, memory reserve or a
particular firmware image's capacity.
