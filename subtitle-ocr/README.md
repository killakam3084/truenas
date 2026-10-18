# Subtitle OCR

One-shot, sequential English subtitle intake for completed MKV files. Extracts
embedded SubRip before considering PGS OCR. No Bazarr, Sonarr, provider accounts,
GPU, Docker socket, or runtime network access required.

## TrueNAS Usage

Create a work directory writable by UID/GID 950 and select a narrowly scoped media
directory. The media mount requires write access to create sidecars; the worker
never opens video files for writing. Do not grant it the entire media dataset.

```sh
export SUBTITLE_MEDIA_DIR='/mnt/cell_block_d/media/video/television/The West Wing S01 br 10bit hevc-d3g'
export SUBTITLE_WORK_DIR=/mnt/cell_block_d/apps/subtitle-ocr/work
mkdir -p "$SUBTITLE_WORK_DIR"
docker compose -f subtitle-ocr/docker-compose.truenas.yml build
docker compose -f subtitle-ocr/docker-compose.truenas.yml run --rm subtitle-ocr --dry-run --pattern '*S01E04*' /media
docker compose -f subtitle-ocr/docker-compose.truenas.yml run --rm subtitle-ocr --pattern '*S01E04*' /media
```

Use `sudo -n docker` on a host where Docker requires elevation; preserve the two
environment variables explicitly when invoking Compose through sudo.

Pass individual container paths to select a batch, or pass a directory and a glob.
`--priority S01E04` processes matching names before other selected files. Directory
scanning is not recursive. `--min-age` defaults to 300 seconds; it is a guard, not
proof of download completion. Invoke only after your downloader/mover reports
completion. No watcher or downloader integration is installed by this MVP.

## Safety And Validation

- Existing bare, English, and English SDH/HI/CC SRT sidecars are skipped, including
  symlinks. Embedded forced tracks are not substituted for full dialogue tracks.
- Supported inputs are English `S_TEXT/UTF8` and `S_HDMV/PGS`. Other formats and
  missing subtitles are reported as failures; there is no audio transcription.
- MKVToolNix extracts tracks. Complete, self-contained PGS display sets are sorted
  by their existing presentation timestamps without changing their bytes. Streams
  with palette/object dependencies or ambiguous show/clear ordering are rejected.
- Every SRT must contain numbered, nonempty, positive-duration, non-overlapping
  cues within the video duration. OCR counts and all start/end times must match
  source PGS presentations within 1 ms. These checks do not prove OCR spelling
  accuracy; review playback before trusting a new source/release.
- The source inode, size, and modification time must remain unchanged throughout
  processing. Results are staged first and published atomically using an exclusive
  hard link in the destination directory. Existing files are never replaced.
- Inherited dataset ACLs are preserved; no chmod, chown, or dataset ACL changes.
- One batch per work directory is enforced using a lock. Failures are logged and
  processing continues; any failure produces a nonzero final exit status.
- The image pins PgsToSrt by digest and verifies the English OCR model checksum.
  Python and system extraction packages are installed at image build time.

`/work/results.jsonl` contains per-file outcomes. Per-file staging directories
retain extracted PGS, normalized PGS, and SRT candidates for inspection. These can
consume tens of MB per episode; remove reviewed staging directories manually.
Reruns skip published sidecars. Nothing rescans Plex automatically; use a library
scan if Plex has not detected the external English SRT.

## Tests

```sh
python3 -m venv /tmp/subtitle-ocr-venv
/tmp/subtitle-ocr-venv/bin/pip install -r subtitle-ocr/requirements.txt
/tmp/subtitle-ocr-venv/bin/python -m unittest discover -s subtitle-ocr -v
```

The image build also runs the unit tests. Runtime is limited to two CPU cores and
1 GB memory by the supplied Compose file. Network downloads happen during build
only. This is an on-demand MVP, not an automatic acquisition or release pipeline.