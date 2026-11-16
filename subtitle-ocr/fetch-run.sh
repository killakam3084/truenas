#!/bin/sh
# Inject OpenSubtitles credentials from Infisical, then run the fetcher.
set -e
exec infisical run --domain="${INFISICAL_DOMAIN}" --projectId="${INFISICAL_PROJECT_ID}" \
  --env="${INFISICAL_ENV:-prod}" --silent -- /opt/venv/bin/python /opt/subtitle-ocr/fetch.py "$@"
