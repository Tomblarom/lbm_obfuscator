from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import lbm_obf as lbm

ROOT = Path(__file__).resolve().parents[1]
TEMP = ROOT / ".cache/tmp"


class SourceTests(unittest.TestCase):
    def test_comments_do_not_damage_strings(self):
        source = '(def msg-text "a;  b ( c ) [ d ] { e }") ; removed\n(print msg-text)'
        self.assertEqual(lbm.minimize_source(source),
                         '(def msg-text "a;  b ( c ) [ d ] { e }")(print msg-text)\n')

    def test_escapes_crlf_and_utf8_are_verbatim(self):
        literal = '"ä;  Ω\\n\\s\\0\\e\\d\\\\\\\"\r\nline"'
        output = lbm.minimize_source('; comment\r\n(print ' + literal + ')\r\n')
        self.assertEqual(output, '(print ' + literal + ')\n')

    def test_character_delimiters_are_not_syntax(self):
        source = r'''(list \#; \#" \#( \#) \#[ \#] \#{ \#} \#' \#` \#, \#\s \#\\)'''
        self.assertEqual(lbm.minimize_source(source), source + '\n')
        self.assertEqual(lbm.minimize_source('\\# '), '\\# \n')

    def test_numeric_spelling_and_dotted_pairs(self):
        source = "(list 0xFF -0xFF 1u32 -1i64 1.0e-3 1.0f64 +1) '(1 . 2)"
        output = lbm.minimize_source(source)
        for token in ('0xFF', '-0xFF', '1u32', '-1i64', '1.0e-3', '1.0f64', '+1', '(1 . 2)'):
            self.assertIn(token, output)
        self.assertEqual(lbm.minimize_source('1 u32 1 e3'), '1 u32 1 e3\n')

    def test_quotes_bindings_unknown_extensions_and_strings_survive(self):
        source = '''(def assist-1 0.1)
        (def long-name 9) (quote (long-name)) '(long-name . protocol-name)
        `(long-name ,long-name ,@(list long-name))
        (let ((long-name 3) (other-name (+ long-name 1))) other-name)
        (eval (str2sym (str-from-n 1 "assist-%d")))
        (new-firmware-extension (speed-age) (pas-last-time))
        (loopwhile-thd "named-thread" t (puts "status msg %.2f settings"))'''
        output = lbm.minimize_source(source)
        self.assertIn('(quote(long-name))', output)
        self.assertIn("'(long-name . protocol-name)", output)
        self.assertIn('"assist-%d"', output)
        self.assertIn('new-firmware-extension', output)
        self.assertIn('"named-thread"', output)
        self.assertIn('(puts "status msg %.2f settings")', output)
        self.assertIn('(other-name(+ long-name 1))', output)

    def test_functional_expressions_are_retained(self):
        source = '(def vt-count 0) (defun update-vt () (setq vt-count (+ vt-count 1))) (print (update-vt))'
        self.assertEqual(lbm.minimize_source(source),
                         '(def vt-count 0)(defun update-vt()(setq vt-count(+ vt-count 1)))(print(update-vt))\n')

    def test_const_directives_stay_on_their_own_lines(self):
        self.assertEqual(lbm.minimize_source('@const-start\n(defun foo () 1)\n@const-end'),
                         '@const-start\n(defun foo()1)\n@const-end\n')
        self.assertEqual(lbm.minimize_source('@const-start (def x 1)'), '@const-start\n(def x 1)\n')

    def test_lists_and_arrays_are_structurally_distinct(self):
        source = "{(var x [0 1 255b]) (list x [|1 'key (2 . 3)|])}"
        output = lbm.minimize_source(source)
        self.assertIn('[0 1 255b]', output)
        self.assertIn("[|1'key(2 . 3)|]", output)

    def test_comments_separate_adjacent_symbols(self):
        self.assertEqual(lbm.minimize_source('hello;gone\nworld'), 'hello world\n')
        self.assertEqual(lbm.minimize_source(';only comment'), '')
        self.assertEqual(lbm.minimize_source(''), '')

    def test_hash_seed_independent_output(self):
        command = [sys.executable, '-c',
                   'import lbm_obf; print(lbm_obf.minimize_source("(def long-name 3) (speed-age) long-name"), end="")']
        outputs = [subprocess.check_output(command, cwd=ROOT,
                                          env={**os.environ, 'PYTHONHASHSEED': seed})
                   for seed in ('0', '1', 'random')]
        self.assertEqual(len(set(outputs)), 1)

    def test_malformed_input_has_location_and_is_rejected(self):
        cases = [
            '(', ')', '(a]', '[|1]', '[1|]', "'", '(a . b c)', '(. a)',
            '[hello]', '[1 (2)]', '"unfinished', '"bad\\q"', '\\#', '\\#\\q',
            '(foo @const-start 1)', '@const-symbol-strings', '#| block |#', '\ufeff(def x 1)',
            '"' + 'x' * 257 + '"', '"' + 'ä' * 129 + '"', 'a' * 257,
            '\\#ä', '1.0e+2', '1.0e-', '0x', '-0x', '12f32', '1.0i32', '#!/usr/bin/lbm',
            ' ; hidden NUL\0\n(def x 1)', '(' * 130 + 'nil' + ')' * 130,
        ]
        for source in cases:
            with self.subTest(source=source[:60]):
                with self.assertRaisesRegex(lbm.MinimizeError, r'fixture.lbm:\d+:\d+:'):
                    lbm.minimize_source(source, 'fixture.lbm')


class FileTests(unittest.TestCase):
    def setUp(self):
        TEMP.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=TEMP)
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)

    def put(self, name, data):
        path = self.directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data.encode('utf-8') if isinstance(data, str) else data)
        return path

    def build(self, source, **options):
        return lbm.compile_file(source, self.directory / 'out/main_min.lbm', **options)

    def test_default_lisp_and_lbm_paths_never_overwrite(self):
        for suffix in ('.lisp', '.lbm'):
            source = self.put('main' + suffix, '(def message "hello;  world") ; comment\n')
            before = source.read_bytes()
            build = lbm.compile_file(source)
            self.assertEqual(build.output.name, 'main_min' + suffix)
            lbm.write_build(build)
            self.assertEqual(source.read_bytes(), before)
            report = json.loads(build.report_path.read_bytes())
            self.assertEqual(report['source_sha256'], lbm.sha256(before))
            self.assertEqual(report['symbol_mapping']['message'], 'message')

    def test_relative_subdirectory_import_and_intervening_side_effect(self):
        dependency = self.put('lib/module.lbm', '; comment\n(def module-value "a  b")\n')
        source = self.put('main.lbm', '''(import "lib/module.lbm" 'code)
        (print "before") (read-eval-program code) (print "after")''')
        build = self.build(source)
        lbm.write_build(build)
        imports = lbm.imports_in(lbm.parse(build.code), build.output)
        self.assertEqual(imports[0].path, dependency)
        self.assertIn('(print "before")(read-eval-program code)(print "after")', build.code)
        self.assertRegex(build.code, r'^\(import "[^\n]+" \'code\)\n')
        self.assertEqual(dependency.read_text(), '; comment\n(def module-value "a  b")\n')

    def test_bundle_preserves_binary_and_code_import_bytes(self):
        data = bytes(range(256))
        binary = self.put('assets/data.bin', data)
        module = self.put('lib/mod.lisp', '@const-start\n(def long-name 7)\n')
        source = self.put('main.lisp', '(import "assets/data.bin" \'data)\n(import "lib/mod.lisp" \'code)\n(read-eval-program code)')
        build = self.build(source, bundle=True)
        lbm.write_build(build)
        imports = lbm.imports_in(lbm.parse(build.code), build.output)
        self.assertEqual([i.path.read_bytes() for i in imports], [data, module.read_bytes()])
        self.assertEqual(binary.read_bytes(), data)
        self.assertTrue(all(path.is_relative_to(build.output.parent) for path in (i.path for i in imports)))

    def test_utf8_sizes_measure_bytes_and_full_payload(self):
        module = self.put('module.lbm', '(def label "Grüße")\n')
        source = self.put('main.lbm', '(import "module.lbm" \'code)\n(print "ä")\n(read-eval-program code)\n')
        build = self.build(source)
        sizes = build.report['sizes']
        self.assertEqual(sizes['source_bytes'], len(source.read_bytes()))
        self.assertEqual(sizes['resolved_payload_bytes'], len(source.read_bytes()) + len(module.read_bytes()))
        self.assertEqual(sizes['output_payload_bytes'], len(build.code.encode()) + len(module.read_bytes()))

    def test_repeated_imports_and_evaluations_are_preserved(self):
        self.put('module.lbm', '(setq counter (+ counter 1))')
        declaration = '(import "module.lbm" \'code)\n(read-eval-program code)\n'
        source = self.put('main.lbm', '(def counter 0)\n' + declaration * 2)
        build = self.build(source)
        self.assertEqual(build.code.count('(read-eval-program code)'), 2)
        self.assertEqual(build.code.count('(import '), 2)
        self.assertEqual(len(build.report['imports']), 2)

    def test_conflicting_import_bindings_fail(self):
        self.put('a.lbm', '1')
        self.put('b.lbm', '2')
        source = self.put('main.lbm', '(import "a.lbm" \'code)\n(import "b.lbm" \'CODE)')
        with self.assertRaisesRegex(lbm.MinimizeError, 'conflicting import binding'):
            self.build(source)

    def test_missing_import_fails_without_output(self):
        source = self.put('main.lbm', '(import "missing.lbm" \'code)\n(read-eval-program code)')
        result = subprocess.run([sys.executable, str(ROOT / 'lbm_obf.py'), str(source),
                                 '-o', str(self.directory / 'output.lbm')], capture_output=True, text=True, timeout=2)
        self.assertEqual(result.returncode, 2)
        self.assertIn('cannot resolve import', result.stderr)
        self.assertIn('main.lbm:1:', result.stderr)
        self.assertFalse((self.directory / 'output.lbm').exists())

    def test_nested_relative_paths_are_resolved_before_explicit_rejection(self):
        self.put('lib/deep/value.lbm', '42')
        self.put('lib/a.lbm', '(import "deep/value.lbm" \'value)')
        source = self.put('main.lbm', '(import "lib/a.lbm" \'a)')
        with self.assertRaisesRegex(lbm.MinimizeError, 'nested import declarations'):
            self.build(source)
        (self.directory / 'lib/deep/value.lbm').unlink()
        with self.assertRaisesRegex(lbm.MinimizeError, 'lib/a.lbm:1:.*deep/value.lbm'):
            self.build(source)

    def test_cycles_terminate_with_chain(self):
        for link in ('main.lbm', '../main.lbm'):
            with self.subTest(link=link):
                if link == 'main.lbm':
                    source = self.put('main.lbm', '(import "main.lbm" \'code)')
                else:
                    source = self.put('main.lbm', '(import "sub/other.lbm" \'code)')
                    self.put('sub/other.lbm', '(import "../main.lbm" \'other)')
                with self.assertRaisesRegex(lbm.MinimizeError, 'import cycle: .* -> .*main.lbm'):
                    self.build(source)

    def test_dynamic_remote_and_nested_executable_imports_fail(self):
        cases = ['(import path \'code)', '(import "foo" code)',
                 '(import "pkg@://vesc_packages/pkg.vescpkg" \'code)',
                 '(import "https://example.invalid/x" \'code)',
                 '(if t (import "module.lbm" \'code))',
                 '(import "module.lbm" \'code) (print "same line")',
                 '(print "same line") (import "module.lbm" \'code)',
                 '(import\n"module.lbm" \'code)',
                 '(import "a\\sb.lbm" \'code)', '(IMPORT "module.lbm" \'code)']
        self.put('module.lbm', '42')
        for text in cases:
            with self.subTest(text=text):
                with self.assertRaises(lbm.MinimizeError):
                    self.build(self.put('main.lbm', text))

    def test_quoted_import_data_and_string_are_not_resolved(self):
        source = self.put('main.lbm', ''''(import "absent.lbm" 'code)
        (quote (import "absent.lbm" 'code))
        "(import absent-file)"''')
        build = self.build(source)
        self.assertEqual(build.report['imports'], [])
        self.assertIn('absent.lbm', build.code)

    def test_direct_symlink_hardlink_and_report_aliases_are_blocked(self):
        source = self.put('main.lbm', '(def original 1)')
        before = source.read_bytes()
        symbolic = self.directory / 'symbolic.lbm'
        symbolic.symlink_to(source)
        hard = self.directory / 'hard.lbm'
        os.link(source, hard)
        for target in (source, symbolic, hard):
            with self.subTest(target=target):
                with self.assertRaisesRegex(lbm.MinimizeError, 'refusing to overwrite input'):
                    lbm.compile_file(source, target)
                with self.assertRaisesRegex(lbm.MinimizeError, 'refusing to overwrite input'):
                    lbm.compile_file(source, self.directory / 'new.lbm', target)
        self.assertEqual(source.read_bytes(), before)

    def test_dependencies_are_also_protected(self):
        module = self.put('module.lisp', '(def original 1)')
        source = self.put('main.lbm', '(import "module.lisp" \'code)')
        with self.assertRaisesRegex(lbm.MinimizeError, 'refusing to overwrite input/dependency'):
            lbm.compile_file(source, module)

    def test_existing_outputs_and_aliased_destinations_fail_before_writing(self):
        source = self.put('main.lbm', '42')
        existing = self.put('result.json', b'existing')
        with self.assertRaisesRegex(lbm.MinimizeError, 'already exists'):
            lbm.compile_file(source, self.directory / 'new.lbm', existing)
        self.assertFalse((self.directory / 'new.lbm').exists())
        with self.assertRaisesRegex(lbm.MinimizeError, 'distinct'):
            lbm.compile_file(source, self.directory / 'new.lbm', self.directory / 'new.lbm')
        with self.assertRaisesRegex(lbm.MinimizeError, 'parent directory'):
            lbm.compile_file(source, self.directory / 'new', self.directory / 'new/report.json')
        self.assertEqual(existing.read_bytes(), b'existing')

    def test_publication_failure_rolls_back_only_new_outputs(self):
        source = self.put('main.lbm', '(def original 1)')
        build = self.build(source)
        original_link = os.link
        calls = 0

        def fail_second(src, dst):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError('simulated filesystem failure')
            original_link(src, dst)

        with patch('lbm_obf.os.link', side_effect=fail_second):
            with self.assertRaisesRegex(lbm.MinimizeError, 'cannot publish'):
                lbm.write_build(build)
        self.assertFalse(build.output.exists())
        self.assertFalse(build.report_path.exists())
        self.assertEqual(source.read_text(), '(def original 1)')
        self.assertEqual(list(build.output.parent.glob('.lbm-min-*')), [])

    def test_racing_new_output_is_never_replaced(self):
        source = self.put('main.lbm', '42')
        build = self.build(source)
        build.output.parent.mkdir(parents=True)
        build.output.write_bytes(b'other writer')
        with self.assertRaisesRegex(lbm.MinimizeError, 'already exists'):
            lbm.write_build(build)
        self.assertEqual(build.output.read_bytes(), b'other writer')

    def test_empty_input_has_finite_zero_size_report(self):
        source = self.put('empty.lisp', '')
        build = self.build(source)
        self.assertEqual(build.report['sizes']['saved_percent'], 0.0)
        self.assertEqual(build.code, '')


if __name__ == '__main__':
    unittest.main()
