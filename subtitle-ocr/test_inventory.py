import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from inventory import classify, group
from worker import digest


def track(codec, language='eng', **properties):
    return {'type': 'subtitles', 'properties': {'codec_id': codec, 'language': language, **properties}}


class InventoryTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.video = self.root / 'Show' / 'episode.mkv'
        self.video.parent.mkdir()
        self.video.write_bytes(b'video')

    def classify_tracks(self, tracks, recognized=True):
        metadata = {'container': {'recognized': recognized}, 'tracks': tracks}
        completed = subprocess.CompletedProcess([], 0, stdout=json.dumps(metadata).encode())
        with patch('inventory.subprocess.run', return_value=completed):
            return classify(self.video, set())['category']

    def test_categories_follow_worker_track_rules(self):
        cases = [
            ([track('S_HDMV/PGS'), track('S_TEXT/UTF8')], 'embedded-text'),
            ([track('S_HDMV/PGS')], 'embedded-pgs'),
            ([track('S_TEXT/ASS')], 'embedded-unsupported'),
            ([track('S_TEXT/UTF8', forced_track=True)], 'forced-only'),
            ([track('S_TEXT/UTF8', tag_number_of_bytes='0')], 'forced-only'),
            ([track('S_TEXT/UTF8', language='spa')], 'no-english'),
            ([track('S_TEXT/UTF8', language='und')], 'embedded-text-untagged'),
            ([track('S_HDMV/PGS', language='und')], 'no-english'),
            ([], 'no-english'),
        ]
        for tracks, expected in cases:
            with self.subTest(expected=expected, tracks=tracks):
                self.assertEqual(self.classify_tracks(tracks), expected)
        self.assertEqual(self.classify_tracks([], recognized=False), 'error')

    def test_sidecars_are_classified_by_ownership_without_inspection(self):
        sidecar = self.video.with_suffix('.en.srt')
        sidecar.write_text('ours')
        with patch('inventory.subprocess.run') as inspect:
            self.assertEqual(classify(self.video, set())['category'], 'sidecar-other')
            self.assertEqual(classify(self.video, {digest(sidecar)})['category'], 'sidecar-own')
            inspect.assert_not_called()

    def test_inspection_failures_are_reported_not_raised(self):
        with patch('inventory.subprocess.run', side_effect=subprocess.CalledProcessError(2, 'mkvmerge')):
            self.assertEqual(classify(self.video, set())['category'], 'error')

    def test_groups_by_first_directory_under_root(self):
        self.assertEqual(group(self.video, self.root), 'Show')
        self.assertEqual(group(self.root / 'loose.mkv', self.root), '(loose files)')


if __name__ == '__main__':
    unittest.main()
