# Main files, imports and VESC payloads

`--bundle` produces a minimized main file and an adjacent `.imports/`
directory. Import files keep their exact bytes. Relative paths in the main
file point to those bundled files.

Pass the main text and its directory to
`CodeLoader::lispPackImports(text, directory, false)` when integrating with
VESC Tool. The last argument disables VESC Tool's separate optional reducer.
This is a packing operation; it does not upload or run the program.

## Encoding

VESC Tool loads source as text and packs the main via `toLocal8Bit()`. Its
locale codec is therefore part of the byte-level contract. The native tests
set UTF-8 explicitly and verify that the main bytes survive unchanged.
A different codec can change non-ASCII literals. Latin-1 output must be
handled with an explicit matching input/packing codec, or used where the
result is ASCII.

Imports are read as raw file bytes when the separate reducer is disabled.
Their string encodings and binary contents are preserved.

## Format

Compatibility is tested against `vedderb/vesc_tool` commit
`dc53c658cbb89a947246034f7a00149cf79abdfc`.

| Part | Representation |
| --- | --- |
| Flags | Two bytes; 0 in the tested path |
| Main | Encoded source followed by NUL |
| Import count | 16-bit big-endian integer |
| Each entry | NUL-terminated label, 32-bit big-endian offset and length |
| Import content | Original bytes plus one NUL byte, aligned to four bytes |

Offsets are relative to the data beginning after the flags. The native
unpacker removes exactly the additional import NUL. An independent decoder
checks ranges, padding, overlap and the same content hashes.

The tested VESC Tool and firmware readers process fewer than 500 imports;
the minimizer rejects more than 499 declarations, including repeats.

VESC Tool retains import declarations in the main text. Firmware binds the
import table as constant arrays before evaluating the source and registers
`import` as a no-op. The local LispBM test host prepares the same imported
bytes without requiring firmware or hardware access.

## Declaration compatibility

VESC Tool recognizes imports from physical text lines. This differs from a
LispBM parser: indentation with tabs, quoted trailing comments and import-like
lines inside quoted data or multiline strings can produce different results.
The minimizer rejects disagreements between the two interpretations.

The supported subset uses literal local paths, quoted symbol bindings,
spaces and lowercase `import`, one declaration per line. Nested import
declarations, package/URL imports and dynamic paths are rejected explicitly.

## Validation and size limits

The native test driver compiles unchanged `codeloader.cpp` method bodies and
the original `VByteArray` implementation. Source hashes and method spans are
recorded during the build. GUI, transport and upload implementations are not
linked. Package imports outside the tested local-file path are rejected by
the test driver.

The minimizer's size report measures source plus import bytes. The packed
`lispData` additionally contains flags, tables, NUL bytes and alignment. A
complete package may also contain QML and other fields; upload framing and
an embedded firmware image add further requirements.

Neither source-size savings nor successful payload packing establish that a
particular firmware or update region has enough free space. That requires
validation against the actual target build.
