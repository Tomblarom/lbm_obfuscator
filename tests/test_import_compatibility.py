"""Regression checks for source encodings and VESC Tool import compatibility."""
import json
from pathlib import Path
import tempfile
import unittest

import lbm_obf as lbm
from tests.test_minimizer import TEMP


class ImportCompatibilityTests(unittest.TestCase):
    def setUp(self):
        TEMP.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=TEMP)
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        (self.directory / 'module.lbm').write_bytes(b'(def preserved 3)\n')

    def build(self, code, **kwargs):
        source = self.directory / 'input.lbm'
        source.write_bytes(code if isinstance(code, bytes) else code.encode())
        return lbm.compile_file(source, self.directory / 'output.lbm', **kwargs)

    def test_quoted_import_comment_is_not_silently_repaired(self):
        text = '(import "module.lbm" \'code) ; "quoted trailing comment"\n'
        with self.assertRaisesRegex(lbm.MinimizeError, 'VESC Tool import recognition differs'):
            self.build(text)
        self.assertFalse((self.directory / 'output.lbm').exists())

    def test_tabs_unsupported_by_the_tool_preprocessor_fail(self):
        cases = ['\t(import "module.lbm" \'code)\n',
                 '(import\t"module.lbm" \'code)\n',
                 '(import "module.lbm"\t\'code)\n',
                 '( \timport "module.lbm" \'code)\n']
        for text in cases:
            with self.subTest(text=text):
                with self.assertRaisesRegex(lbm.MinimizeError, 'VESC Tool import recognition differs'):
                    self.build(text)

    def test_import_looking_quoted_data_is_rejected_for_packaging(self):
        text = "'(data\n(import \"module.lbm\" 'code)\n)"
        with self.assertRaisesRegex(lbm.MinimizeError, 'VESC Tool import recognition differs'):
            self.build(text)
        # Text-only compaction still keeps the data; file compilation enforces
        # the additional, textual VESC Tool preprocessing contract.
        self.assertIn('module.lbm', lbm.minimize_source(text))

    def test_import_looking_multiline_string_is_rejected_for_packaging(self):
        text = '(def text "first line\n(import \\"module.lbm\\" \'code)\nlast line")'
        with self.assertRaisesRegex(lbm.MinimizeError, 'VESC Tool import recognition differs'):
            self.build(text)

    def test_space_indentation_and_unquoted_comments_work(self):
        build = self.build('  (  import  "module.lbm"  \'code ) ; ordinary comment\n(read-eval-program code)')
        self.assertEqual(build.code.splitlines()[0], '(import "module.lbm" \'code)')

    def test_utf8_is_strict_and_never_guessed(self):
        with self.assertRaisesRegex(lbm.MinimizeError, 'cannot decode.*utf-8'):
            self.build(b'; legacy byte source \xdf\n(def value "\xfc")\n')
        self.assertFalse((self.directory / 'output.lbm').exists())

    def test_explicit_latin1_keeps_literal_bytes_and_reports_the_codec(self):
        original = b'; legacy byte source \xdf\n(def label "Gr\xfc\xdfe;  ")\n(print label)\n'
        build = self.build(original, encoding='latin-1')
        lbm.write_build(build)
        output = build.output.read_bytes()
        self.assertIn(b'"Gr\xfc\xdfe;  "', output)
        self.assertNotIn(b'\xc3\xbc', output)
        self.assertEqual((self.directory / 'input.lbm').read_bytes(), original)
        report = json.loads(build.report_path.read_bytes())
        self.assertEqual(report['source_encoding'], 'latin-1')
        self.assertEqual(report['output_encoding'], 'latin-1')
        self.assertEqual(report['report_encoding'], 'utf-8')
        self.assertEqual(report['sizes']['output_source_bytes'], len(output))

    def test_string_limit_counts_declared_bytes(self):
        text = '(def label "' + '\xff' * 200 + '")'
        self.assertEqual(lbm.minimize_source(text, encoding='latin-1').encode('latin-1'),
                         b'(def label "' + b'\xff' * 200 + b'")\n')
        with self.assertRaisesRegex(lbm.MinimizeError, '256-byte'):
            lbm.minimize_source(text)
        with self.assertRaisesRegex(lbm.MinimizeError, 'cannot be represented'):
            lbm.minimize_source('(def label "Ω")', encoding='latin-1')

    def test_arbitrary_encoding_conversion_is_not_enabled(self):
        with self.assertRaisesRegex(lbm.MinimizeError, 'unsupported source encoding'):
            self.build('(def value 1)', encoding='utf-16')

    def test_import_count_counts_repeated_declarations(self):
        declaration = '(import "module.lbm" \'code)\n'
        accepted = self.build(declaration * 499)
        self.assertEqual(len(accepted.report['imports']), 499)
        with self.assertRaisesRegex(lbm.MinimizeError, 'at most 499 import declarations'):
            self.build(declaration * 500)


if __name__ == '__main__':
    unittest.main()
