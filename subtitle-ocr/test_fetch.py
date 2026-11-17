from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from fetch import ATTEMPTS_PER_VIDEO, MIN_SCORE, Fetcher, QuotaExhausted, choose, opensubtitles_hash, tidy
from worker import ValidationError


class Language:
    def __init__(self, alpha3):
        self.alpha3 = alpha3


class Subtitle:
    def __init__(self, id_, score, hash_match=False, language='eng', foreign_only=False, machine=False,
                 content=b''):
        self.id, self.score, self.hash_match = id_, score, hash_match
        self.language, self.foreign_only, self.machine_generated = Language(language), foreign_only, machine
        self.content = content

    def get_matches(self, video):
        return {'hash'} if self.hash_match else set()


class Episode:
    def __init__(self):
        self.hashes = {}


class Pool:
    def __init__(self, listed, download_ok=True, discard_on_download=False):
        self.listed, self.download_ok, self.discard_on_download = listed, download_ok, discard_on_download
        self.discarded_providers, self.downloaded = set(), []

    def list_subtitles(self, video, languages):
        return self.listed

    def download_subtitle(self, subtitle):
        self.downloaded.append(subtitle.id)
        if self.discard_on_download:
            self.discarded_providers.add('opensubtitlescom')
            return False
        subtitle.content = (b'1\n00:00:01,000 --> 00:00:02,000\nHello\n\n'
                            b'2\n00:00:03,000 --> 00:00:04,000\nThere\n\n')
        return self.download_ok


def score(subtitle, video):
    return subtitle.score


class FetchTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.video = self.root / 'Show.S01E01.mkv'
        self.video.write_bytes(b'\0' * 200_000)
        probe = patch('fetch.probe_duration_ms', return_value=5000.0)
        probe.start()
        self.addCleanup(probe.stop)

    def fetcher(self, pool, sync_result=None, limit=10, misaligned=()):
        def sync(video, source, destination):
            destination.write_bytes(source.read_bytes())
            if source.stem.removeprefix('downloaded-') in misaligned:
                return {'sync_was_successful': False, 'offset_seconds': -2.2, 'framerate_scale_factor': 1.0}
            return sync_result or {'sync_was_successful': True, 'offset_seconds': 1.5,
                                   'framerate_scale_factor': 1.0}
        return Fetcher(pool, score, lambda path, name: Episode(), limit, Language('eng'), sync)

    def test_hash_matches_size_plus_little_endian_word_sums(self):
        self.assertEqual(opensubtitles_hash(self.video), '%016x' % 200_000)
        self.video.write_bytes(struct.pack('<Q', 5) + b'\0' * 199_992)
        self.assertEqual(opensubtitles_hash(self.video), '%016x' % (200_000 + 5))

    def test_choose_filters_and_prefers_hash_matches(self):
        listed = [Subtitle('low', MIN_SCORE['episode'] - 1), Subtitle('good', 700), Subtitle('hash', 10, True),
                  Subtitle('spa', 900, language='spa'), Subtitle('forced', 900, foreign_only=True),
                  Subtitle('ai', 900, machine=True)]
        self.assertEqual([item[2].id for item in choose(listed, None, score, 'episode')], ['hash', 'good'])

    def test_tidy_drops_blank_cues_and_trims_small_overlaps_only(self):
        text, trimmed = tidy('1\n00:00:01,000 --> 00:00:03,000\nA\n\n2\n00:00:02,500 --> 00:00:04,000\nB\n\n'
                             '3\n00:00:05,000 --> 00:00:06,000\n \n\n')
        self.assertEqual(trimmed, 1)
        self.assertEqual(text, '1\n00:00:01,000 --> 00:00:02,500\nA\n\n2\n00:00:02,500 --> 00:00:04,000\nB\n\n')
        with self.assertRaises(ValidationError):
            tidy('1\n00:00:01,000 --> 00:00:09,000\nA\n\n2\n00:00:02,000 --> 00:00:04,000\nB\n\n')

    def test_publishes_aligned_download_without_touching_video(self):
        before = self.video.read_bytes()
        details = {}
        result = self.fetcher(Pool([Subtitle('good', 700)])).process(self.video, self.root, 0, False, '', details)
        self.assertEqual((result['status'], result['cues']), ('published', 2))
        self.assertEqual(self.video.with_suffix('.en.srt').read_bytes(),
                         (Path(result['staging']) / 'subtitle.en.srt').read_bytes())
        self.assertEqual((details['subtitle_id'], details['sync']['offset_seconds']), ('good', 1.5))
        self.assertEqual(self.video.read_bytes(), before)

    def test_untrustworthy_alignment_is_withheld(self):
        fetcher = self.fetcher(Pool([Subtitle('good', 700)]), {'sync_was_successful': False, 'offset_seconds': 0})
        with self.assertRaises(ValidationError):
            fetcher.process(self.video, self.root, 0, False, '', {})
        self.assertFalse(self.video.with_suffix('.en.srt').exists())

    def test_misaligned_download_falls_through_to_next_candidate(self):
        pool = Pool([Subtitle('broadcast', 760), Subtitle('web', 750)])
        details = {}
        result = self.fetcher(pool, misaligned={'broadcast'}).process(self.video, self.root, 0, False, '', details)
        self.assertEqual((result['status'], details['subtitle_id'], pool.downloaded),
                         ('published', 'web', ['broadcast', 'web']))
        self.assertEqual([attempt['sync_was_successful'] for attempt in details['attempts']], [False, True])

    def test_alignment_failures_stop_after_attempt_limit(self):
        pool = Pool([Subtitle(str(index), 700) for index in range(5)])
        misaligned = {str(index) for index in range(5)}
        with self.assertRaisesRegex(ValidationError, 'any candidate'):
            self.fetcher(pool, misaligned=misaligned).process(self.video, self.root, 0, False, '', {})
        self.assertEqual(len(pool.downloaded), ATTEMPTS_PER_VIDEO)
        self.assertFalse(self.video.with_suffix('.en.srt').exists())

    def test_quota_exhaustion_stops_the_run(self):
        pool = Pool([Subtitle('good', 700)], discard_on_download=True)
        with self.assertRaises(QuotaExhausted):
            self.fetcher(pool).process(self.video, self.root, 0, False, '', {})
        with self.assertRaises(QuotaExhausted):
            self.fetcher(Pool([Subtitle('good', 700)]), limit=0).process(self.video, self.root, 0, False, '', {})

    def test_failed_downloads_try_limited_candidates_then_report_not_found(self):
        pool = Pool([Subtitle(str(index), 700) for index in range(5)], download_ok=False)
        result = self.fetcher(pool).process(self.video, self.root, 0, False, '', {})
        self.assertEqual((result['status'], len(pool.downloaded)), ('not-found', ATTEMPTS_PER_VIDEO))

    def test_existing_sidecar_and_dry_run_never_download(self):
        pool = Pool([Subtitle('good', 700)])
        self.assertEqual(self.fetcher(pool).process(self.video, self.root, 0, True, '', {})['status'], 'planned')
        self.video.with_suffix('.srt').write_text('theirs')
        self.assertEqual(self.fetcher(pool).process(self.video, self.root, 0, False, '', {})['status'], 'skipped')
        self.assertEqual(pool.downloaded, [])


if __name__ == '__main__':
    unittest.main()
