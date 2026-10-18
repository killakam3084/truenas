# Changelog

## [Unreleased]

### Added
- Containerized, offline English SRT extraction and PGS OCR for completed MKVs.
- Presentation-order normalization, source-timing validation, atomic sidecar
  publication, existing-subtitle skips, priority ordering, and JSONL batch reports.
- Configurable CPU, memory, and per-engine OCR thread limits for performance tuning.
- Per-file elapsed-time reporting and a measured 2-versus-8-CPU OCR comparison.

### Fixed
- Limit directory glob matches to MKVs so newly created sidecars never become inputs.