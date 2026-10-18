# Changelog

## [Unreleased]

### Added
- Containerized, offline English SRT extraction and PGS OCR for completed MKVs.
- Presentation-order normalization, source-timing validation, atomic sidecar
  publication, existing-subtitle skips, priority ordering, and JSONL batch reports.

### Fixed
- Limit directory glob matches to MKVs so newly created sidecars never become inputs.