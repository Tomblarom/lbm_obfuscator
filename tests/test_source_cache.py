"""Integrity and offline checks for the public VESC Tool source cache."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from tests.test_minimizer import ROOT, TEMP

sys.path.insert(0, str(ROOT / 'tools'))
import vesc_sources


class SourceCacheTests(unittest.TestCase):
    def setUp(self):
        TEMP.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=TEMP)
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.data = b'verified source\n'
        self.pin = {'commit': '1' * 40, 'files': {'source.cpp': vesc_sources.sha(self.data)}}
        for name, value in [('SOURCES', self.directory), ('LOCK', self.pin)]:
            guard = patch.object(vesc_sources, name, value)
            guard.start()
            self.addCleanup(guard.stop)
        self.network = patch.object(vesc_sources, 'urlopen', side_effect=AssertionError('unexpected network'))
        self.urlopen = self.network.start()
        self.addCleanup(self.network.stop)

    def test_verified_cache_is_reused_offline(self):
        source = self.directory / 'source.cpp'
        source.write_bytes(self.data)
        self.assertEqual(vesc_sources.prepare(offline=True), self.directory)
        self.assertEqual(source.read_bytes(), self.data)
        self.urlopen.assert_not_called()

    def test_changed_cache_is_rejected_without_overwrite(self):
        source = self.directory / 'source.cpp'
        source.write_bytes(b'local modification')
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            vesc_sources.prepare(offline=True)
        self.assertEqual(source.read_bytes(), b'local modification')
        self.urlopen.assert_not_called()

    def test_missing_offline_source_does_not_fetch(self):
        with self.assertRaisesRegex(RuntimeError, 'missing in offline mode'):
            vesc_sources.prepare(offline=True)
        self.assertFalse((self.directory / 'source.cpp').exists())
        self.urlopen.assert_not_called()


if __name__ == '__main__':
    unittest.main()
