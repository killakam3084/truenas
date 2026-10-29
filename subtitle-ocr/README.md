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
export SUBTITLE_REVISION="$(git rev-parse HEAD)"
mkdir -p "$SUBTITLE_WORK_DIR"
docker compose -f subtitle-ocr/docker-compose.truenas.yml build
export SUBTITLE_IMAGE_ID="$(docker image inspect --format '{{.Id}}' truenas/subtitle-ocr:0.1.0)"
docker compose -f subtitle-ocr/docker-compose.truenas.yml run --rm subtitle-ocr --dry-run --pattern '*S01E04*' /media
docker compose -f subtitle-ocr/docker-compose.truenas.yml run --rm subtitle-ocr --pattern '*S01E04*' /media
```

Use `sudo -n docker` on a host where Docker requires elevation; preserve the
`SUBTITLE_*` environment variables explicitly when invoking Compose through sudo.

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

`/work/results.jsonl` contains per-file outcomes, grouped by run ID, with deployed
revision, supplied image ID, OCR thread limit, and available cgroup CPU/memory
limits. The revision is baked into the image at build time; image ID must be
supplied at runtime as shown above. Unspecified identities are recorded as
`unknown`; no Docker socket is required.

Per-file staging directories retain MKV metadata, a `result.json` report,
extracted PGS, normalized PGS, and SRT candidates for inspection. Failures retain
the processing phase, staging path, and structured validation details, including
the cue index and timestamps when applicable. OCR results also record the model
SHA256. These can
consume tens of MB per episode; remove reviewed staging directories manually.
Reruns skip published sidecars. Nothing rescans Plex automatically; use a library
scan if Plex has not detected the external English SRT.

## Tests

```sh
python3 -m venv /tmp/subtitle-ocr-venv
/tmp/subtitle-ocr-venv/bin/pip install -r subtitle-ocr/requirements.txt
/tmp/subtitle-ocr-venv/bin/python -m unittest discover -s subtitle-ocr -v
```

The image build also runs the unit tests. Runtime defaults to two CPU cores and
1 GB memory. Override `SUBTITLE_CPUS`, `SUBTITLE_MEMORY`, and
`SUBTITLE_OCR_THREADS` (Tesseract's per-engine OpenMP limit, default 2) when
invoking Compose. The converter also processes cues in parallel, so raising the
OpenMP limit is not the same as assigning more CPUs and can oversubscribe them.
Network downloads happen during build only. This is an on-demand MVP, not an
automatic acquisition or release pipeline.

## NAS Benchmark

Single-run comparison on the dual Xeon E5-2680 v4 NAS (28 physical cores, 56 logical
CPUs), using the same 932-cue episode 4 normalized PGS stream, 2 GiB memory, and
`SUBTITLE_OCR_THREADS=2`:

| CPU Quota | OCR Container Wall Time | Output |
|---|---|---|
| 2 CPUs | 128.8 seconds | Identical to validated reference |
| 8 CPUs | 33.2 seconds | Identical to validated reference |

This was a 3.88x speedup for OCR only, including container startup but excluding
extraction and normalization. It is not a repeated statistical benchmark. Use
`SUBTITLE_CPUS=8 SUBTITLE_MEMORY=2g` for this host's batch, keeping the conservative
defaults for other hosts. Pass these variables explicitly through `sudo env` when
needed. JSONL outcomes include `elapsed_seconds` for each complete intake operation.

## Season 1 Intake Results

The West Wing episodes 03-22 were exercised through this MVP. Episode 04 was
published first, with 932 validated cues. The remaining batch used 8 CPUs and
2 GiB memory, one episode at a time:

- 19 of 20 requested episodes published with validated cue counts, source timing,
  and matching staged/published hashes. No MKVs were changed or sidecars replaced.
- The 18 successful files timed at 8 CPUs took 33.2-46.2 seconds each for the full
  workflow, with a median of 38.2 seconds. Episode 04's initial 2-CPU run is excluded.
- Episode 17 was withheld because cue 941 had no recognized text. A manual retry
  using `tessdata_best` also failed the same gate. Its staged candidates remain for
  review; there is deliberately no sidecar for that episode and no silent cue drop.

This verifies the publication gates and throughput, not the spelling accuracy of
every OCR cue. Episode 02 was separately confirmed in playback by the user. Source
PGS subtitles remain available for the withheld episode.