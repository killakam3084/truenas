FROM debian:bookworm-slim@sha256:99c0b25c46d0214d5a2091092e7908907dcaecd6a962cde0ac700acee222b6f3 AS deps

RUN apt-get update \
    && apt-get install --no-install-recommends -y python3 python3-venv mkvtoolnix libtesseract5 ffmpeg curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/subtitle-ocr
COPY requirements.txt ./
RUN python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt \
    && mkdir tessdata \
    && curl --fail --location --output tessdata/eng.traineddata https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/main/eng.traineddata \
    && echo '7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2  tessdata/eng.traineddata' | sha256sum -c -
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 OMP_THREAD_LIMIT=1 HOME=/tmp

# Networked downloader: Infisical CLI for credentials.
FROM deps AS fetch
COPY requirements-fetch.txt ./
RUN /opt/venv/bin/pip install --no-cache-dir -r requirements-fetch.txt
COPY --from=infisical/cli@sha256:ef5cd9bef770e1d13acfa18414a65719a262c4b7681735086416852f1574d019 /bin/infisical /usr/local/bin/infisical
COPY *.py fetch-run.sh ./
COPY testdata ./testdata
RUN /opt/venv/bin/python -m unittest -v
ARG SUBTITLE_REVISION=unknown
ENV SUBTITLE_REVISION=${SUBTITLE_REVISION}
USER 950:950
ENTRYPOINT ["/bin/sh", "/opt/subtitle-ocr/fetch-run.sh"]
CMD ["/media"]

# Offline OCR worker (default target).
FROM deps AS ocr
COPY *.py ./
COPY testdata ./testdata
RUN /opt/venv/bin/python -m unittest -v
ARG SUBTITLE_REVISION=unknown
ENV SUBTITLE_REVISION=${SUBTITLE_REVISION}
USER 950:950
ENTRYPOINT ["/opt/venv/bin/python", "/opt/subtitle-ocr/worker.py"]
CMD ["/media"]
