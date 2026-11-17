"""Download English subtitles for videos with none, align them to the audio, and publish safely."""
import argparse
from datetime import timedelta
import fcntl
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import time
import uuid

import srt

from worker import (MIN_CUES_PER_MINUTE, ValidationError, digest, existing_sidecar, fingerprint, publish,
                    runtime_context, synchronize, validate)

VIDEO_SUFFIXES = {'.mkv', '.mp4', '.m4v', '.avi', '.ts', '.m2ts'}
PROVIDER = 'opensubtitlescom'
# Episode: series+season+episode (486+54+54); movie: title+year (162+54). A file-hash match always passes.
MIN_SCORE = {'episode': 594, 'movie': 216}
MAX_OFFSET_SECONDS = 30
MAX_OVERLAP_MS = 2000
ATTEMPTS_PER_VIDEO = 3


class QuotaExhausted(Exception):
    pass


def opensubtitles_hash(path):
    """The OpenSubtitles file hash: size plus 64-bit sums of the first and last 64 KiB."""
    size = path.stat().st_size
    chunk = 65536
    total = size
    with path.open('rb') as source:
        for offset in (0, max(0, size - chunk)):
            source.seek(offset)
            data = source.read(chunk)
            data += b'\0' * (-len(data) % 8)
            total += sum(struct.unpack(f'<{len(data) // 8}Q', data))
    return f'{total & 0xFFFFFFFFFFFFFFFF:016x}'


def choose(subtitles, video, compute_score, kind):
    """Eligible English subtitles, best first."""
    eligible = []
    for subtitle in subtitles:
        if getattr(subtitle.language, 'alpha3', None) != 'eng':
            continue
        if getattr(subtitle, 'foreign_only', False) or getattr(subtitle, 'machine_generated', False):
            continue
        score = compute_score(subtitle, video)
        hash_match = 'hash' in subtitle.get_matches(video)
        if hash_match or score >= MIN_SCORE[kind]:
            eligible.append((hash_match, score, subtitle))
    eligible.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return eligible


def tidy(text):
    """Drop blank cues, order by time, and trim small overlaps; returns (srt text, trimmed count)."""
    try:
        cues = sorted((cue for cue in srt.parse(text) if cue.content.strip()), key=lambda cue: (cue.start, cue.end))
    except (srt.SRTParseError, ValueError) as error:
        raise ValidationError(f'Downloaded subtitle is not valid SRT: {error}') from None
    trimmed = 0
    for previous, current in zip(cues, cues[1:]):
        if current.start < previous.end:
            overlap = (previous.end - current.start) / timedelta(milliseconds=1)
            if overlap > MAX_OVERLAP_MS or current.start <= previous.start:
                raise ValidationError('Downloaded subtitle has large overlapping cues',
                                      start_ms=current.start / timedelta(milliseconds=1), overlap_ms=overlap)
            previous.end = current.start
            trimmed += 1
    for cue in cues:
        cue.content = cue.content.strip()
    return srt.compose(cues, reindex=True), trimmed


def probe_duration_ms(video):
    output = subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                                      '-of', 'default=noprint_wrappers=1:nokey=1', str(video)])
    return float(output) * 1000


class Fetcher:
    def __init__(self, pool, compute_score, scan, limit, language, sync=synchronize):
        self.pool, self.compute_score, self.scan, self.sync = pool, compute_score, scan, sync
        self.limit, self.language, self.downloads = limit, language, 0

    def download(self, candidates):
        """Yield each successfully downloaded candidate, best first, within the attempt and quota limits."""
        for hash_match, score, subtitle in candidates[:ATTEMPTS_PER_VIDEO]:
            if self.downloads >= self.limit:
                raise QuotaExhausted(f'Per-run download limit of {self.limit} reached')
            self.downloads += 1
            ok = self.pool.download_subtitle(subtitle)
            if PROVIDER in self.pool.discarded_providers:
                raise QuotaExhausted('Provider discarded (daily quota exhausted or authentication failed)')
            if ok and subtitle.content:
                yield hash_match, score, subtitle

    def process(self, path, work, min_age, dry_run, hint, details):
        details['phase'] = 'inspection'
        if path.suffix.lower() not in VIDEO_SUFFIXES or path.is_symlink() or not path.is_file():
            raise ValueError('Input must be a regular non-symlink video file')
        sidecar = existing_sidecar(path)
        if sidecar:
            return {'status': 'skipped', 'reason': 'existing sidecar', 'subtitle': str(sidecar)}
        before = fingerprint(path)
        if time.time() - path.stat().st_mtime < min_age:
            raise ValueError('Input is too recent; wait for downloading/moving to finish')
        duration_ms = probe_duration_ms(path)
        video = self.scan(path, f'{hint}/{path.name}' if hint else None)
        file_hash = opensubtitles_hash(path)
        video.hashes.update(opensubtitles=file_hash, opensubtitlescom=file_hash)
        kind = 'episode' if type(video).__name__ == 'Episode' else 'movie'
        details.update(duration_ms=duration_ms, guessed=str(video), kind=kind, source_fingerprint=list(before),
                       phase='search')
        listed = self.pool.list_subtitles(video, {self.language})
        if PROVIDER in self.pool.discarded_providers:
            raise QuotaExhausted('Provider discarded during search')
        candidates = choose(listed, video, self.compute_score, kind)
        details['candidates'] = [{'id': subtitle.id, 'score': score, 'hash_match': hash_match,
                                  'release': getattr(subtitle, 'release', None)}
                                 for hash_match, score, subtitle in candidates[:ATTEMPTS_PER_VIDEO]]
        if not candidates:
            return {'status': 'not-found', 'listed': len(listed)}
        if dry_run:
            return {'status': 'planned'}
        details['phase'] = 'download'
        staging, attempts = None, []
        # Subtitles cut for another release (broadcast vs extended) fail alignment; fall through to the next.
        for hash_match, score, subtitle in self.download(candidates):
            if staging is None:
                staging = Path(tempfile.mkdtemp(prefix=f'{path.stem[:30]}-', dir=work))
                details.update(staging=str(staging), provider=PROVIDER)
            raw, synced = staging / f'downloaded-{subtitle.id}.srt', staging / f'synced-{subtitle.id}.srt'
            raw.write_bytes(subtitle.content)
            details['phase'] = 'synchronization'
            sync = self.sync(path, raw, synced)
            attempts.append({'subtitle_id': subtitle.id, **sync})
            details['attempts'] = attempts
            if sync.get('sync_was_successful') and abs(sync.get('offset_seconds') or 0) <= MAX_OFFSET_SECONDS:
                break
        else:
            if not attempts:
                return {'status': 'not-found', 'reason': 'downloads failed', 'listed': len(listed)}
            raise ValidationError('Audio alignment not trustworthy for any candidate', attempts=attempts)
        candidate = staging / 'subtitle.en.srt'
        details.update(candidate=str(candidate), subtitle_id=subtitle.id, score=score, hash_match=hash_match,
                       sync=sync, phase='validation')
        text, trimmed = tidy(synced.read_text(encoding='utf-8-sig'))
        with candidate.open('x', encoding='utf-8') as output:
            output.write(text)
        count = validate(candidate, duration_ms)
        details['trimmed_overlaps'] = trimmed
        if count < MIN_CUES_PER_MINUTE * duration_ms / 60000:
            raise ValidationError('Downloaded subtitle too sparse for full dialogue', cues=count)
        if fingerprint(path) != before:
            raise ValueError('Source changed during processing; refusing publication')
        if existing_sidecar(path):
            return {'status': 'skipped', 'reason': 'sidecar appeared during processing'}
        destination = path.with_suffix('.en.srt')
        details['phase'] = 'publication'
        publish(candidate, destination)
        if candidate.read_bytes() != destination.read_bytes():
            raise ValueError('Published subtitle differs from validated output')
        return {'status': 'published', 'method': 'download', 'cues': count, 'sha256': digest(candidate),
                'subtitle': str(destination), 'staging': str(staging)}


def main():
    parser = argparse.ArgumentParser(description='Download, align, and publish missing English subtitles.')
    parser.add_argument('inputs', nargs='+', type=Path)
    parser.add_argument('--pattern', default='*')
    parser.add_argument('--title-hint', default='', help='show or movie name when file names lack it')
    parser.add_argument('--limit', type=int, default=10, help='maximum downloads this run (provider quota)')
    parser.add_argument('--work', type=Path, default=Path('/work'))
    parser.add_argument('--min-age', type=int, default=300)
    parser.add_argument('--dry-run', action='store_true', help='search and report only; no downloads')
    arguments = parser.parse_args()
    from babelfish import Language
    from subliminal import region, scan_video
    from subliminal.core import ProviderPool
    from subliminal.score import compute_score
    region.configure('dogpile.cache.memory')
    videos = set()
    for source in arguments.inputs:
        if source.is_dir():
            videos.update(path for path in source.glob(arguments.pattern)
                          if path.suffix.lower() in VIDEO_SUFFIXES and path.is_file())
        else:
            videos.add(source)
    if not videos:
        parser.error('No input files matched')
    config = {PROVIDER: {'username': os.environ['OPENSUBTITLES_USERNAME'],
                         'password': os.environ['OPENSUBTITLES_PASSWORD'],
                         'apikey': os.environ['OPENSUBTITLES_API_KEY']}}
    provenance, run_id, failed = runtime_context(), uuid.uuid4().hex, False
    with (arguments.work / 'fetch.lock').open('a') as lock, ProviderPool(providers=[PROVIDER],
                                                                          provider_configs=config) as pool:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fetcher = Fetcher(pool, compute_score, lambda path, name: scan_video(str(path), name=name), arguments.limit,
                          Language('eng'))
        quota = None
        for video in sorted(videos):
            started = time.perf_counter()
            details = {'run_id': run_id, 'provenance': provenance}
            print(f'PROCESSING {video}', flush=True)
            if quota:
                result = {'status': 'skipped', 'reason': quota}
            else:
                try:
                    result = fetcher.process(video, arguments.work, arguments.min_age, arguments.dry_run,
                                             arguments.title_hint, details)
                except QuotaExhausted as error:
                    quota = str(error)
                    result = {'status': 'skipped', 'reason': quota}
                except Exception as error:
                    failed = True
                    result = {'status': 'failed', 'error': str(error), 'error_type': type(error).__name__,
                              'error_details': getattr(error, 'details', {})}
            result = {**details, **result, 'downloads_used': fetcher.downloads}
            result.update(video=str(video), timestamp=time.time(),
                          elapsed_seconds=round(time.perf_counter() - started, 3))
            encoded = json.dumps(result, default=str)
            print(encoded, flush=True)
            if result.get('staging'):
                (Path(result['staging']) / 'result.json').write_text(encoded + '\n')
            with (arguments.work / 'results.jsonl').open('a') as report:
                report.write(encoded + '\n')
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
