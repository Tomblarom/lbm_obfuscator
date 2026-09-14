from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import lbm_obf as lbm
from tests import runtime
from tests.test_minimizer import TEMP

FIXTURES = Path(__file__).parent / 'fixtures'


class EquivalenceTests(unittest.TestCase):
    def setUp(self):
        TEMP.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=TEMP)
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)

    def compare(self, name, source):
        minimized = self.directory / (name + '_min.lbm')
        minimized.write_bytes(lbm.minimize_source(source.read_bytes().decode('utf-8'), str(source)).encode())
        original = runtime.run([source])
        output = runtime.run([minimized])
        self.assertEqual(original, output)
        self.assertIn('RESULT test-ok', original)
        runtime.record(name, source.read_bytes(), minimized.read_bytes(), original)

    def test_regression_programs_execute_equally(self):
        for source in sorted(FIXTURES.glob('*.lbm')):
            with self.subTest(case=source.stem):
                self.compare(source.stem, source)

    def test_imports_preserve_array_contents_repeated_calls_and_const_channels(self):
        library = self.directory / 'lib/module.lisp'
        library.parent.mkdir()
        content = b'; byte-observable comment\n@const-start\n(defun increment-count () (setq counter (+ counter 1)))\n(increment-count)\n'
        library.write_bytes(content)
        source = self.directory / 'main.lbm'
        source.write_text('''(def counter 0)
(import "lib/module.lisp" 'code)
(test-assert (= (bufget-u8 code 0) 59))
(test-emit 'before counter)
(read-eval-program code)
(test-emit 'between counter)
(read-eval-program code)
(test-emit 'after counter)
(def mutable-state '(1 2))
(setcar mutable-state 3)
(test-assert (eq mutable-state '(3 2)))
(test-assert (= counter 2))
(test-emit (buflen code) mutable-state counter)
'test-ok
''')
        build = lbm.compile_file(source, self.directory / 'bundle/result.lbm', bundle=True)
        lbm.write_build(build)
        original = runtime.prepare(source, self.directory / 'original-native.lbm')
        result = runtime.prepare(build.output, self.directory / 'result-native.lbm')
        original_log = runtime.run([original.path], original.imports)
        result_log = runtime.run([result.path], result.imports)
        self.assertEqual(original_log, result_log)
        self.assertIn('TRACE after 2', result_log)
        self.assertEqual(library.read_bytes(), content)
        self.assertEqual(result.imports[0][1].read_bytes(), content)
        runtime.record('imports', source.read_bytes(), build.output.read_bytes(), original_log,
                       sizes=build.report['sizes'])

    def test_crlf_escapes_have_identical_runtime_bytes(self):
        source = self.directory / 'crlf.lbm'
        source.write_bytes(b'(def msg "a;\r\nb\\0c")\r\n(test-assert (= (buflen msg) 8))\r\n(test-emit msg)\r\n\'test-ok\r\n')
        self.compare('crlf', source)

    def test_explicit_latin1_keeps_native_string_bytes(self):
        source = self.directory / 'latin1.lbm'
        source.write_bytes(b'; single-byte comment \xdf\n(def label "Gr\xfc\xdfe;  ")\n'
                           b'(test-assert (= (buflen label) 9))\n'
                           b'(test-assert (= (bufget-u8 label 2) 252))\n'
                           b'(test-assert (= (bufget-u8 label 3) 223))\n'
                           b'(test-emit (buflen label) (bufget-u8 label 2) (bufget-u8 label 3))\n'
                           b"'test-ok\n")
        build = lbm.compile_file(source, self.directory / 'latin1_min.lbm', encoding='latin-1')
        lbm.write_build(build)
        original = runtime.run([source])
        minimized = runtime.run([build.output])
        self.assertEqual(original, minimized)
        self.assertIn('TRACE 9', original)
        self.assertIn('RESULT test-ok', original)
        runtime.record('latin1', source.read_bytes(), build.output.read_bytes(), original)

    def test_native_reader_agrees_on_upstream_syntax_corpus(self):
        corpus = runtime.ROOT / '.cache/sources/lispbm/tests/tests'
        patterns = ('test_comments_*.lisp', 'test_quote_*.lisp', 'test_qq_*.lisp',
                    'test_characters.lisp', 'test_array_syntax_*.lisp',
                    'test_high_level_array_syntax_*.lisp', 'test_let_*.lisp',
                    'test_deconstruct_let_*.lisp', 'test_progn_var_*.lisp',
                    'test_setq_*.lisp', 'test_str_from_n_*.lisp')
        files = sorted({file for pattern in patterns for file in corpus.glob(pattern)})
        self.assertGreater(len(files), 50, 'Pinned upstream source corpus is required')
        imports, checks = [], []
        checked, rejected = [], []
        for index, source in enumerate(files):
            original = source.read_bytes()
            try:
                compact = lbm.minimize_source(original.decode('utf-8'), str(source))
            except lbm.MinimizeError as exc:
                # Explicitly unsupported syntax is recorded, never emitted.
                rejected.append({'file': source.name, 'reason': str(exc)})
                continue
            output = self.directory / f'corpus-{index}.lbm'
            output.write_bytes(compact.encode())
            imports.extend([(f'test-original-{index}', source), (f'test-output-{index}', output)])
            checks.append(f'(test-assert (eq (read-program test-original-{index}) (read-program test-output-{index})))')
            checked.append(source.name)
        self.assertGreater(len(checked), 50)
        driver = self.directory / 'reader-driver.lbm'
        driver.write_text('\n'.join(checks) + "\n'test-ok\n")
        transcript = runtime.run([driver], imports)
        self.assertIn('RESULT test-ok', transcript)
        runtime.record('upstream-reader', driver.read_bytes(), driver.read_bytes(), transcript,
                       checked=checked, explicitly_rejected=rejected)


if __name__ == '__main__':
    unittest.main()
