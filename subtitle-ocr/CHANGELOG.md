# Changelog

## [Unreleased]

### Added
- Run IDs, image/revision/model provenance, retained per-file metadata and failure
  reports, and structured cue-level validation diagnostics.
- Containerized, offline English SRT extraction and PGS OCR for completed MKVs.
- Presentation-order normalization, source-timing validation, atomic sidecar
  publication, existing-subtitle skips, priority ordering, and JSONL batch reports.
- Configurable CPU, memory, and per-engine OCR thread limits for performance tuning.
- Per-file elapsed-time reporting and a measured 2-versus-8-CPU OCR comparison.
- Documented season intake results: 19 validated publications, one safely withheld
  OCR failure, and a 38.2-second median full-workflow time at 8 CPUs.

### Fixed
- Limit directory glob matches to MKVs so newly created sidecars never become inputs.