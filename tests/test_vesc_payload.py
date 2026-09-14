"""Native VESC Tool preprocessing/packing checks; never opens a device."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

import lbm_obf as lbm
from tests.test_minimizer import ROOT, TEMP

sys.path.insert(0, str(ROOT / 'tools'))
import vesc_payload


@unittest.skipUnless(vesc_payload.HOST.exists(), 'Build the VESC Tool payload test host to enable native packaging checks')
class VescPayloadTests(unittest.TestCase):
    def setUp(self):
        TEMP.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=TEMP)
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)

    def test_native_pack_unpack_preserves_import_bytes_and_alignment(self):
        data = bytes(range(256))
        module = b'@const-start\n(def long-name "a;  b")\n'
        (self.directory / 'binary.bin').write_bytes(data)
        (self.directory / 'module.lbm').write_bytes(module)
        source = self.directory / 'main.lbm'
        source.write_text('(import "binary.bin" \'bytes)\n(import "module.lbm" \'code)\n(read-eval-program code)\n')
        build = lbm.compile_file(source, self.directory / 'bundle/main_min.lbm', bundle=True)
        lbm.write_build(build)
        report = vesc_payload.pack(build.output, self.directory / 'payload.bin')
        self.assertTrue(report['main_bytes_preserved'])
        self.assertFalse(report['reduce_lisp'])
        self.assertEqual([i['sha256'] for i in report['imports']], [lbm.sha256(data), lbm.sha256(module)])
        self.assertTrue(all(item['offset_without_flags'] % 4 == 0 for item in report['layout']))
        self.assertEqual([item['stored_bytes'] for item in report['layout']], [257, len(module) + 1])
        self.assertGreater(report['format_overhead_bytes'], 0)

    def test_python_guard_matches_the_pinned_native_line_recognizer(self):
        text = '\n'.join([
            '(import "module.lbm" \'code)',
            '  (  import  "module.lbm"  \'code ) ; simple comment',
            '\t(import "module.lbm" \'code)',
            '(import\t"module.lbm" \'code)',
            '(import "module.lbm"\t\'code)',
            '(import "module.lbm" \'code) ; "quoted comment"',
            ';(import "module.lbm" \'code)',
            '(IMPORT "module.lbm" \'code)',
        ])
        source = self.directory / 'lines.lbm'
        source.write_text(text)
        native = vesc_payload.import_lines(source)
        actual = {item['line']: (item['path'], item['tag']) for item in native}
        self.assertEqual(actual, lbm.vesc_import_lines(text))
        self.assertNotIn(3, actual)
        self.assertNotIn(4, actual)
        self.assertEqual(actual[5][1], '\tcode')

    def test_native_packer_demonstrates_quoted_comment_failure(self):
        (self.directory / 'module.lbm').write_bytes(b'1')
        source = self.directory / 'bad.lbm'
        source.write_text('(import "module.lbm" \'code) ; "quoted comment"\n')
        with self.assertRaisesRegex(ValueError, 'refused the import layout'):
            vesc_payload.pack(source, self.directory / 'bad.bin')
        with self.assertRaisesRegex(lbm.MinimizeError, 'VESC Tool import recognition differs'):
            lbm.compile_file(source, self.directory / 'bad_min.lbm')

    def test_qt_local_codec_is_an_explicit_byte_boundary(self):
        source = self.directory / 'unicode.lbm'
        source.write_text('(print "Grüße")\n', encoding='utf-8')
        utf8 = vesc_payload.pack(source, self.directory / 'utf8.bin')
        legacy = vesc_payload.pack(source, self.directory / 'latin1.bin', codec='ISO-8859-1')
        self.assertTrue(utf8['main_bytes_preserved'])
        self.assertFalse(legacy['main_bytes_preserved'])
        self.assertNotEqual(utf8['main_payload_sha256'], legacy['main_payload_sha256'])

    def test_source_decoding_is_not_silent_replacement(self):
        source = self.directory / 'raw.lbm'
        source.write_bytes(b'(print "\xdf")\n')
        with self.assertRaisesRegex(ValueError, 'valid UTF-8'):
            vesc_payload.pack(source, self.directory / 'raw.bin')

    def test_native_import_limit_matches_the_firmware_format(self):
        (self.directory / 'module.lbm').write_bytes(b'1')
        source = self.directory / 'many.lbm'
        source.write_text('(import "module.lbm" \'code)\n' * 500)
        with self.assertRaisesRegex(ValueError, 'Invalid import count'):
            vesc_payload.pack(source, self.directory / 'too-many.bin')
        with self.assertRaisesRegex(lbm.MinimizeError, 'at most 499'):
            lbm.compile_file(source, self.directory / 'many_min.lbm')


if __name__ == '__main__':
    unittest.main()
