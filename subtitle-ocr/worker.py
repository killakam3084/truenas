import argparse
from datetime import timedelta
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
import time
import uuid

import srt

import ocr


class ValidationError(ValueError):
    def __init__(self, message, **details):
        super().__init__(message)
        self.details = details


def runtime_context():
    limits = {}
    for name in ('cpu.max', 'memory.max'):
        path = Path('/sys/fs/cgroup') / name
        if path.is_file():
            limits[name] = path.read_text().strip()
    return {'image_id': os.environ.get('SUBTITLE_IMAGE_ID', 'unknown'),
            'revision': os.environ.get('SUBTITLE_REVISION', 'unknown'),
            'ocr_threads': os.environ.get('OMP_THREAD_LIMIT', 'unknown'),
            'resource_limits': limits}


# Tesseract reads the subtitle font's capital I as a pipe or a lone lowercase l.
MISREAD_I = re.compile(r'\||(?<![A-Za-z])l(?![A-Za-z])')


def correct_ocr(text):
    return MISREAD_I.subn('I', text)


def ocr_subtitle(normalized, intervals, staging, details):
    shown = [data for _, data, visible in presentations(normalized) if visible]
    if len(shown) != len(intervals):
        raise ValueError('PGS presentations differ from cue intervals')
    model = ocr.TESSDATA / 'eng.traineddata'
    workers = ocr.worker_count()
    details.update(phase='ocr', expected_cues=len(intervals), ocr_engine=f'tesseract {ocr.version()}',
                   ocr_workers=workers, model_sha256=hashlib.sha256(model.read_bytes()).hexdigest())
    results = ocr.recognize_all(shown, workers)
    cues, report, unread, corrections = [], [], [], 0
    for position, ((start, end), result) in enumerate(zip(intervals, results), 1):
        text, count = correct_ocr(result.text)
        corrections += count
        report.append({'cue': position, 'start_ms': start, 'end_ms': end, 'raw': result.text,
                       'text': text, 'unread_regions': len(result.unread)})
        for region, image in enumerate(result.unread, 1):
            (staging / f'cue-{position:04d}-region-{region}.pgm').write_bytes(image)
        if result.unread:
            unread.append({'cue': position, 'start_ms': start, 'end_ms': end,
                           'regions': len(result.unread), 'text': text})
        cues.append(srt.Subtitle(position, timedelta(milliseconds=start), timedelta(milliseconds=end), text))
    (staging / 'ocr.json').write_text(json.dumps(report, indent=1) + '\n')
    details.update(ocr_corrections=corrections, ocr_unread=unread)
    if unread:
        first = unread[0]
        raise ValidationError(f'Unread text region in cue {first["cue"]}', position=first['cue'],
                              cue_index=first['cue'], start_ms=first['start_ms'], end_ms=first['end_ms'],
                              empty_content=not first['text'], unread_cues=len(unread))
    return srt.compose(cues, reindex=False)


def presentations(path):
    display_sets = []
    current = []
    segment_types = set()
    timestamp = None
    visible = False
    with path.open('rb') as source:
        while header := source.read(13):
            if len(header) != 13:
                raise ValueError('Truncated PGS header')
            magic, presentation, decoding, kind, size = struct.unpack('>2sIIBH', header)
            payload = source.read(size)
            if magic != b'PG' or len(payload) != size:
                raise ValueError('Invalid or truncated PGS segment')
            if kind == 0x16:
                if current or len(payload) < 11:
                    raise ValueError('Invalid PGS display-set boundary')
                timestamp = presentation
                visible = payload[10] != 0
            elif not current:
                raise ValueError('PGS display set does not start with PCS')
            current.append(header + payload)
            segment_types.add(kind)
            if kind == 0x80:
                if visible and not {0x14, 0x15}.issubset(segment_types):
                    raise ValueError('PGS palette/object dependencies are unsupported')
                display_sets.append((timestamp, b''.join(current), visible))
                current = []
                segment_types = set()
    if current or not display_sets:
        raise ValueError('Incomplete or empty PGS stream')
    return display_sets


def normalize(source, destination):
    original = presentations(source)
    ordered = sorted(original, key=lambda display_set: display_set[0])
    intervals = []
    active = None
    for timestamp, data, visible in ordered:
        if visible:
            if active is not None:
                raise ValueError('Overlapping or dependent PGS presentations')
            active = timestamp
        else:
            if active is None or timestamp <= active:
                raise ValueError('Invalid PGS show/clear ordering')
            intervals.append((active / 90, timestamp / 90))
            active = None
    if active is not None:
        raise ValueError('Final subtitle has no clear event')
    with destination.open('xb') as output:
        for timestamp, data, visible in ordered:
            output.write(data)
    if sorted(presentations(destination)) != sorted(original):
        raise ValueError('PGS display-set bytes changed')
    return intervals


def validate(path, duration_ms, intervals=None):
    cues = list(srt.parse(path.read_text(encoding='utf-8-sig')))
    if not cues:
        raise ValueError('No subtitle cues')
    previous_end = 0
    for position, cue in enumerate(cues, 1):
        start = cue.start.total_seconds() * 1000
        end = cue.end.total_seconds() * 1000
        if cue.index != position or not cue.content.strip():
            raise ValidationError(f'Invalid cue number/content at {position}',
                                  position=position, cue_index=cue.index,
                                  start_ms=start, end_ms=end,
                                  empty_content=not cue.content.strip())
        if not 0 <= start < end <= duration_ms or start < previous_end:
            raise ValidationError(f'Invalid or overlapping timing at cue {position}',
                                  position=position, cue_index=cue.index,
                                  start_ms=start, end_ms=end, previous_end_ms=previous_end,
                                  duration_ms=duration_ms)
        previous_end = end
    if intervals is not None:
        if len(cues) != len(intervals):
            raise ValidationError('OCR cue count differs from PGS',
                                  actual_cues=len(cues), expected_cues=len(intervals))
        for cue, (start, end) in zip(cues, intervals):
            if max(abs(cue.start.total_seconds() * 1000 - start),
                   abs(cue.end.total_seconds() * 1000 - end)) > 1:
                raise ValidationError('OCR timing differs from PGS by more than 1ms',
                                      cue_index=cue.index, expected_start_ms=start,
                                      expected_end_ms=end,
                                      actual_start_ms=cue.start.total_seconds() * 1000,
                                      actual_end_ms=cue.end.total_seconds() * 1000)
    return len(cues)


def select_track(metadata):
    candidates = []
    for track in metadata['tracks']:
        properties = track.get('properties', {})
        language = properties.get('language_ietf') or properties.get('language', '')
        if track['type'] != 'subtitles' or language.split('-')[0] not in ('en', 'eng'):
            continue
        if properties.get('forced_track'):
            continue
        if str(properties.get('tag_number_of_bytes', 'unknown')) == '0':
            continue
        codec = properties.get('codec_id')
        if codec in ('S_TEXT/UTF8', 'S_HDMV/PGS'):
            candidates.append(track)
    if not candidates:
        raise ValueError('No supported non-forced English SRT/PGS track')
    return min(candidates, key=lambda track: (
        track['properties']['codec_id'] != 'S_TEXT/UTF8',
        not track['properties'].get('default_track', False), track['id']))


def existing_sidecar(video):
    for language in ('', '.en', '.eng'):
        for variant in ('', '.sdh', '.hi', '.cc'):
            candidate = video.with_suffix(f'{language}{variant}.srt')
            if candidate.exists() or candidate.is_symlink():
                return candidate
    return None


def publish(source, destination, replace=False):
    temporary = destination.parent / f'.subtitle-ocr-{uuid.uuid4().hex}.tmp'
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
        with os.fdopen(descriptor, 'wb') as output, source.open('rb') as input_file:
            shutil.copyfileobj(input_file, output)
            output.flush()
            os.fsync(output.fileno())
        if replace:
            os.replace(temporary, destination)
        else:
            os.link(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def owned_hashes(work):
    """Hashes of every sidecar this tool has produced, from reports and retained staging."""
    owned = set()
    results = work / 'results.jsonl'
    if results.is_file():
        with results.open() as lines:
            owned.update(json.loads(line).get('sha256') for line in lines)
    for name in ('subtitle.en.srt', 'subtitle.en.corrected.srt'):
        owned.update(digest(path) for path in work.glob(f'*/{name}'))
    owned.discard(None)
    return owned


def fingerprint(path):
    details = path.stat()
    return details.st_dev, details.st_ino, details.st_size, details.st_mtime_ns


def process(video, work, min_age, dry_run, details=None, owned=None):
    if details is None:
        details = {}
    details['phase'] = 'inspection'
    if video.suffix.lower() != '.mkv' or video.is_symlink() or not video.is_file():
        raise ValueError('Input must be a regular non-symlink file')
    destination = video.with_suffix('.en.srt')
    sidecar = existing_sidecar(video)
    replacing = None
    if sidecar:
        if (owned is None or sidecar != destination or sidecar.is_symlink()
                or digest(sidecar) not in owned):
            reason = 'existing sidecar' if owned is None else 'existing sidecar not produced by this tool'
            return {'status': 'skipped', 'reason': reason, 'subtitle': str(sidecar)}
        replacing = digest(sidecar)
        details['replacing_sha256'] = replacing
    before = fingerprint(video)
    if time.time() - video.stat().st_mtime < min_age:
        raise ValueError('Input is too recent; wait for downloading/moving to finish')
    with video.open('rb') as source:
        if source.read(4) != b'\x1a\x45\xdf\xa3':
            raise ValueError('Invalid MKV header')
    metadata = json.loads(subprocess.check_output(['mkvmerge', '-J', str(video)]))
    track = select_track(metadata)
    duration_ms = metadata['container']['properties']['duration'] / 1_000_000
    details.update(track=track, duration_ms=duration_ms, source_fingerprint=list(before))
    if dry_run:
        return {'status': 'planned', 'track': track['id'], 'codec': track['properties']['codec_id'],
                'replace': replacing is not None}
    staging = Path(tempfile.mkdtemp(prefix=f'{video.stem[:30]}-', dir=work))
    candidate = staging / 'subtitle.en.srt'
    details.update(staging=str(staging), candidate=str(candidate), phase='extraction')
    (staging / 'metadata.json').write_text(json.dumps(metadata, indent=2) + '\n')
    intervals = None
    if track['properties']['codec_id'] == 'S_TEXT/UTF8':
        subprocess.run(['mkvextract', str(video), 'tracks', f'{track["id"]}:{candidate}'], check=True)
        method = 'extracted-srt'
    else:
        extracted = staging / 'original.sup'
        normalized = staging / 'normalized.sup'
        subprocess.run(['mkvextract', str(video), 'tracks', f'{track["id"]}:{extracted}'], check=True)
        details['phase'] = 'normalization'
        intervals = normalize(extracted, normalized)
        text = ocr_subtitle(normalized, intervals, staging, details)
        with candidate.open('x', encoding='utf-8') as output:
            output.write(text)
        method = 'pgs-ocr'
    details.update(phase='validation', method=method)
    count = validate(candidate, duration_ms, intervals)
    if fingerprint(video) != before:
        raise ValueError('Source changed during processing; refusing publication')
    current = existing_sidecar(video)
    sha256 = digest(candidate)
    if replacing is None and current:
        return {'status': 'skipped', 'reason': 'sidecar appeared during processing'}
    if replacing is not None:
        if current != destination or digest(destination) != replacing:
            return {'status': 'skipped', 'reason': 'sidecar changed during processing'}
        if sha256 == replacing:
            return {'status': 'unchanged', 'method': method, 'cues': count, 'sha256': sha256,
                    'subtitle': str(destination), 'staging': str(staging)}
        shutil.copyfile(destination, staging / 'previous.en.srt')
    details['phase'] = 'publication'
    publish(candidate, destination, replace=replacing is not None)
    if candidate.read_bytes() != destination.read_bytes():
        raise ValueError('Published subtitle differs from validated output')
    return {'status': 'replaced' if replacing else 'published', 'method': method, 'cues': count,
            'sha256': sha256, 'subtitle': str(destination), 'staging': str(staging)}


def main():
    parser = argparse.ArgumentParser(description='Extract English SRT or OCR PGS from completed MKVs.')
    parser.add_argument('inputs', nargs='+', type=Path)
    parser.add_argument('--pattern', default='*.mkv')
    parser.add_argument('--priority', default='')
    parser.add_argument('--work', type=Path, default=Path('/work'))
    parser.add_argument('--min-age', type=int, default=300)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--replace-own', action='store_true',
                        help='regenerate .en.srt sidecars whose bytes match an earlier output of this tool')
    arguments = parser.parse_args()
    arguments.work.mkdir(parents=True, exist_ok=True)
    videos = set()
    for source in arguments.inputs:
        if source.is_dir():
            videos.update(path for path in source.glob(arguments.pattern)
                          if path.suffix.lower() == '.mkv' and path.is_file())
        else:
            videos.add(source)
    if not videos:
        parser.error('No input files matched')
    failed = False
    provenance = runtime_context()
    run_id = uuid.uuid4().hex
    with (arguments.work / 'worker.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        owned = owned_hashes(arguments.work) if arguments.replace_own else None
        for video in sorted(videos, key=lambda path: (arguments.priority not in path.name, str(path))):
            print(f'PROCESSING {video}', flush=True)
            started = time.perf_counter()
            details = {'run_id': run_id, 'provenance': provenance}
            try:
                result = process(video, arguments.work, arguments.min_age, arguments.dry_run, details, owned)
            except Exception as error:
                failed = True
                result = {'status': 'failed', 'error': str(error),
                          'error_type': type(error).__name__,
                          'error_details': getattr(error, 'details', {})}
            result = {**details, **result}
            result.update(video=str(video), timestamp=time.time(),
                          elapsed_seconds=round(time.perf_counter() - started, 3))
            encoded = json.dumps(result)
            print(encoded, flush=True)
            if result.get('staging'):
                (Path(result['staging']) / 'result.json').write_text(encoded + '\n')
            with (arguments.work / 'results.jsonl').open('a') as report:
                report.write(encoded + '\n')
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())