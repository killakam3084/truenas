import ctypes.util
from pathlib import Path
import tempfile
import unittest

import ocr

FIXTURE = Path(__file__).parent / 'testdata' / 'lone-i.sup'


class WorkerCountTests(unittest.TestCase):
    def test_uses_cgroup_quota_and_falls_back_when_unlimited(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        quota = Path(directory.name) / 'cpu.max'
        quota.write_text('1600000 100000\n')
        self.assertEqual(ocr.worker_count(quota), 16)
        quota.write_text('150000 100000\n')
        self.assertEqual(ocr.worker_count(quota), 2)
        quota.write_text('max 100000\n')
        self.assertGreaterEqual(ocr.worker_count(quota), 1)


@unittest.skipUnless(ctypes.util.find_library('tesseract') and ocr.TESSDATA.is_dir(),
                     'requires libtesseract and the bundled model (runs in the image build)')
class TesseractTests(unittest.TestCase):
    def test_recovers_lone_capital_i_with_single_line_fallback(self):
        engine = ocr.Tesseract()
        self.addCleanup(engine.close)
        result = engine.recognize(FIXTURE.read_bytes())
        self.assertEqual((result.text, result.fallback), ('I...', True))
        self.assertTrue(result.image.startswith(b'P5\n'))

    def test_process_pool_preserves_order(self):
        results = ocr.recognize_all([FIXTURE.read_bytes()] * 3, workers=2)
        self.assertEqual([result.text for result in results], ['I...'] * 3)


if __name__ == '__main__':
    unittest.main()
