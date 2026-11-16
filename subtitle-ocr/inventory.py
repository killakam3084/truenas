import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import time

from worker import digest, existing_sidecar, owned_hashes, untagged_text_tracks

VIDEO_SUFFIXES = {'.mkv', '.mp4', '.m4v', '.avi', '.ts', '.m2ts'}
SUPPORTED = {'S_TEXT/UTF8': 'embedded-text', 'S_HDMV/PGS': 'embedded-pgs'}


def english(track):
    properties = track.get('properties', {})
    language = properties.get('language_ietf') or properties.get('language', '')
    return track['type'] == 'subtitles' and language.split('-')[0] in ('en', 'eng')


def classify(video, owned):
    sidecar = existing_sidecar(video)
    if sidecar:
        mine = not sidecar.is_symlink() and digest(sidecar) in owned
        return {'category': 'sidecar-own' if mine else 'sidecar-other', 'sidecar': sidecar.name}
    try:
        metadata = json.loads(subprocess.run(['mkvmerge', '-J', str(video)], capture_output=True,
                                             check=True, timeout=120).stdout)
    except (subprocess.SubprocessError, ValueError) as error:
        return {'category': 'error', 'error': f'{type(error).__name__}: {error}'[:200]}
    if not metadata.get('container', {}).get('recognized'):
        return {'category': 'error', 'error': 'container not recognized'}
    tracks = [track for track in metadata.get('tracks', []) if english(track)]
    codecs = sorted({track['properties'].get('codec_id', track.get('codec', '?')) for track in tracks})
    full = [track for track in tracks if not track['properties'].get('forced_track')
            and str(track['properties'].get('tag_number_of_bytes', 'unknown')) != '0']
    for codec, category in SUPPORTED.items():
        if any(track['properties'].get('codec_id') == codec for track in full):
            return {'category': category, 'codecs': codecs}
    if full:
        return {'category': 'embedded-unsupported', 'codecs': codecs}
    if untagged_text_tracks(metadata):
        return {'category': 'embedded-text-untagged', 'codecs': codecs}
    return {'category': 'forced-only' if tracks else 'no-english', 'codecs': codecs}


def group(path, root):
    parts = path.relative_to(root).parts
    return parts[0] if len(parts) > 1 else '(loose files)'


def main():
    parser = argparse.ArgumentParser(description='Read-only English subtitle inventory.')
    parser.add_argument('roots', nargs='+', type=Path)
    parser.add_argument('--work', type=Path, default=Path('/work'))
    parser.add_argument('--workers', type=int, default=os.cpu_count() or 4)
    arguments = parser.parse_args()
    videos = sorted((root, path) for root in arguments.roots for path in root.rglob('*')
                    if path.suffix.lower() in VIDEO_SUFFIXES and path.is_file() and not path.is_symlink())
    owned = owned_hashes(arguments.work)
    started = time.perf_counter()
    with ThreadPoolExecutor(arguments.workers) as pool:
        results = list(pool.map(lambda item: classify(item[1], owned), videos))
    report = arguments.work / f'inventory-{time.strftime("%Y%m%dT%H%M%S")}.jsonl'
    totals, groups = Counter(), defaultdict(Counter)
    with report.open('x') as output:
        for (root, path), result in zip(videos, results):
            result.update(root=root.name, group=group(path, root), video=str(path.relative_to(root)))
            output.write(json.dumps(result) + '\n')
            totals[result['category']] += 1
            groups[(root.name, result['group'])][result['category']] += 1
    print(f'{len(videos)} videos in {time.perf_counter() - started:.1f}s -> {report}')
    for category, count in totals.most_common():
        print(f'  {category:22} {count:6}')
    print('\nGroups needing work (embedded or download):')
    for (root, name), counts in sorted(groups.items()):
        pending = {key: value for key, value in counts.items() if not key.startswith('sidecar')}
        if pending:
            print(f'  {root}/{name}: ' + ', '.join(f'{key}={value}' for key, value in sorted(pending.items())))


if __name__ == '__main__':
    main()
