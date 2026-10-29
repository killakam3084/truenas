import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from worker import ValidationError, existing_sidecar, main, normalize, presentations, process, publish, runtime_context, select_track, validate


def segment(kind, payload, timestamp):
    return struct.pack('>2sIIBH', b'PG', timestamp, 0, kind, len(payload)) + payload


def display_set(timestamp, visible):
    payload = b'\0' * 10 + bytes([int(visible)])
    result = segment(0x16, payload, timestamp)
    if visible:
        result += segment(0x14, b'palette', timestamp)
        result += segment(0x15, b'object', timestamp)
    return result + segment(0x80, b'', timestamp)


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_reorders_complete_sets_without_changing_bytes(self):
        source = self.root / 'source.sup'
        destination = self.root / 'sorted.sup'
        source.write_bytes(display_set(90000, True) + display_set(270000, True)
                           + display_set(180000, False) + display_set(360000, False))
        intervals = normalize(source, destination)
        self.assertEqual(intervals, [(1000, 2000), (3000, 4000)])
        self.assertEqual(sorted(presentations(source)), sorted(presentations(destination)))

    def test_rejects_truncation_and_overlapping_presentations(self):
        source = self.root / 'source.sup'
        source.write_bytes(b'PG')
        with self.assertRaises(ValueError):
            normalize(source, self.root / 'invalid.sup')
        source.write_bytes(display_set(90000, True) + display_set(180000, True))
        with self.assertRaises(ValueError):
            normalize(source, self.root / 'invalid.sup')

    def test_rejects_palette_dependencies(self):
        source = self.root / 'source.sup'
        source.write_bytes(segment(0x16, b'\0' * 10 + b'\1', 90000) + segment(0x80, b'', 90000))
        with self.assertRaises(ValueError):
            normalize(source, self.root / 'invalid.sup')

    def test_validates_source_timing_and_rejects_bad_cues(self):
        subtitle = self.root / 'subtitle.srt'
        subtitle.write_text('1\n00:00:01,000 --> 00:00:02,000\nHello\n\n')
        self.assertEqual(validate(subtitle, 3000, [(1000, 2000)]), 1)
        with self.assertRaises(ValueError):
            validate(subtitle, 3000, [(1000, 2100)])
        for timing in ('00:00:02,000 --> 00:00:01,000', '00:00:01,000 --> 00:00:01,000'):
            subtitle.write_text(f'1\n{timing}\nHello\n\n')
            with self.assertRaises(ValueError):
                validate(subtitle, 3000)

    def test_selects_text_before_pgs_and_ignores_empty_forced_tracks(self):
        def track(track_id, codec, **properties):
            return {'id': track_id, 'type': 'subtitles', 'properties': {
                'language': 'eng', 'codec_id': codec, **properties}}
        metadata = {'tracks': [track(2, 'S_HDMV/PGS', default_track=True),
                               track(3, 'S_TEXT/UTF8', forced_track=True),
                               track(4, 'S_TEXT/UTF8', tag_number_of_bytes='0'),
                               track(5, 'S_TEXT/UTF8')]}
        self.assertEqual(select_track(metadata)['id'], 5)
        metadata['tracks'] = metadata['tracks'][:1]
        self.assertEqual(select_track(metadata)['id'], 2)

    def test_empty_ocr_cue_reports_index_and_timestamp(self):
        subtitle = self.root / 'empty.srt'
        subtitle.write_text('1\n00:00:01,000 --> 00:00:02,000\n \n\n')
        with self.assertRaises(ValidationError) as failure:
            validate(subtitle, 3000, [(1000, 2000)])
        self.assertEqual(failure.exception.details['cue_index'], 1)
        self.assertEqual(failure.exception.details['start_ms'], 1000)
        self.assertTrue(failure.exception.details['empty_content'])

    def test_batch_failure_preserves_staging_and_provenance(self):
        video = self.root / 'video.mkv'
        video.touch()
        staging = self.root / 'staging'
        staging.mkdir()

        def fail(source, work, min_age, dry_run, details):
            details.update(staging=str(staging), phase='validation')
            raise ValidationError('Empty cue', cue_index=941, start_ms=1000)

        arguments = ['worker', '--work', str(self.root / 'work'), str(video)]
        with patch('sys.argv', arguments), patch('worker.process', side_effect=fail):
            self.assertEqual(main(), 1)
        result = json.loads((staging / 'result.json').read_text())
        self.assertEqual(result['staging'], str(staging))
        self.assertEqual(result['phase'], 'validation')
        self.assertEqual(result['error_details']['cue_index'], 941)
        self.assertIn('image_id', result['provenance'])
        self.assertEqual(json.loads((self.root / 'work/results.jsonl').read_text()), result)

    def test_runtime_context_records_deployment_identity(self):
        environment = {'SUBTITLE_IMAGE_ID': 'sha256:test-image',
                       'SUBTITLE_REVISION': 'test-revision', 'OMP_THREAD_LIMIT': '2'}
        with patch.dict('os.environ', environment):
            context = runtime_context()
        self.assertEqual(context['image_id'], environment['SUBTITLE_IMAGE_ID'])
        self.assertEqual(context['revision'], environment['SUBTITLE_REVISION'])
        self.assertEqual(context['ocr_threads'], '2')
        self.assertIsInstance(context['resource_limits'], dict)

    def test_atomic_publication_never_overwrites_and_cleans_temporary(self):
        source = self.root / 'source.srt'
        destination = self.root / 'video.en.srt'
        source.write_bytes(b'validated')
        publish(source, destination)
        self.assertEqual(destination.read_bytes(), b'validated')
        source.write_bytes(b'replacement')
        with self.assertRaises(FileExistsError):
            publish(source, destination)
        self.assertEqual(destination.read_bytes(), b'validated')
        self.assertEqual(list(self.root.glob('.subtitle-ocr-*')), [])
        self.assertEqual(existing_sidecar(self.root / 'video.mkv'), destination)

    def test_existing_sidecar_skips_before_inspection(self):
        video = self.root / 'video.mkv'
        video.write_bytes(b'\x1a\x45\xdf\xa3')
        video.with_suffix('.en.srt').write_bytes(b'existing')
        with patch('worker.subprocess.check_output') as inspect:
            self.assertEqual(process(video, self.root, 0, False)['status'], 'skipped')
            inspect.assert_not_called()

    def test_broad_directory_pattern_selects_only_mkvs(self):
        video = self.root / 'S01E04.mkv'
        video.touch()
        video.with_suffix('.en.srt').touch()
        arguments = ['worker', '--work', str(self.root / 'work'),
                     '--pattern', '*S01E04*', str(self.root)]
        with patch('sys.argv', arguments), \
                patch('worker.process', return_value={'status': 'skipped'}) as process_file:
            self.assertEqual(main(), 0)
            self.assertEqual(process_file.call_count, 1)
            self.assertEqual(process_file.call_args.args[0], video)

    def test_changed_source_is_not_published(self):
        video = self.root / 'video.mkv'
        video.write_bytes(b'\x1a\x45\xdf\xa3')
        metadata = {'container': {'properties': {'duration': 3_000_000_000}},
                    'tracks': [{'id': 2, 'type': 'subtitles', 'properties': {
                        'language': 'eng', 'codec_id': 'S_TEXT/UTF8'}}]}

        def extract(command, check):
            output = Path(command[-1].split(':', 1)[1])
            output.write_text('1\n00:00:01,000 --> 00:00:02,000\nHello\n\n')
            video.write_bytes(video.read_bytes() + b'changed')

        with patch('worker.subprocess.check_output', return_value=json.dumps(metadata)), \
                patch('worker.subprocess.run', side_effect=extract):
            with self.assertRaisesRegex(ValueError, 'Source changed'):
                process(video, self.root, 0, False)
        self.assertFalse(video.with_suffix('.en.srt').exists())


if __name__ == '__main__':
    unittest.main()