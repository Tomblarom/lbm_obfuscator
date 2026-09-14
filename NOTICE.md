# Source and license provenance

This project continues Tomblarom/lbm_obfuscator. Its historical regular-
expression implementation derives from
[Relys/vesc_pkg/float_accessories/lispbm_minimizer.py](https://github.com/Relys/vesc_pkg/blob/fd7ac274c297b8a7c68fcf16d07e47267dd3d87b/float_accessories/lispbm_minimizer.py).
That repository provides GNU GPL version 3 in its root LICENSE. A verbatim
copy is retained in [LICENSES/GPL-3.0.txt](LICENSES/GPL-3.0.txt). The current
implementation replaces the unsafe transformations while preserving upstream
attribution; no new ownership of upstream material is asserted.

The native test runtime uses LispBM 0.36.0 vendored by `vedderb/bldc` at
`20cbb362687291242ab90b99f25fbfe8835540fc`, LispBM tree
`8364d3d29596f1a6663d017cfbab52de9ed57be6`. It is principally copyright Joel
Svensson and other contributors, under GPL-3.0-or-later as marked in its
sources. Downloaded LICENSE and THIRD-PARTY-NOTICES.md files remain with those
sources. The local C test host credits the initialization examples it adapts.

Payload compatibility tests use `vedderb/vesc_tool` commit
`dc53c658cbb89a947246034f7a00149cf79abdfc`. The test build extracts four unchanged
methods from `codeloader.cpp` and compiles the original `vbytearray.cpp` and
`vbytearray.h` with QtCore. Their Benjamin Vedder copyright and
GPL-3.0-or-later notices are preserved. Method spans and hashes are recorded in
the local build manifest. Transport and upload code are not linked.

Pinned references are listed in `tools/lispbm-lock.json` and
`tools/vesc-tool-lock.json`. Downloaded sources, toolchain packages, binaries
and generated test output are kept in the ignored local cache.
