FROM debian:bookworm-slim@sha256:99c0b25c46d0214d5a2091092e7908907dcaecd6a962cde0ac700acee222b6f3

RUN apt-get update \
    && apt-get install --no-install-recommends -y python3 python3-venv mkvtoolnix libtesseract5 curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/subtitle-ocr
COPY requirements.txt ./
RUN python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt \
    && mkdir tessdata \
    && curl --fail --location --output tessdata/eng.traineddata https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/main/eng.traineddata \
    && echo '7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2  tessdata/eng.traineddata' | sha256sum -c -
COPY *.py ./
COPY testdata ./testdata
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 OMP_THREAD_LIMIT=1
RUN /opt/venv/bin/python -m unittest -v
ARG SUBTITLE_REVISION=unknown
ENV SUBTITLE_REVISION=${SUBTITLE_REVISION}
USER 950:950
ENTRYPOINT ["/opt/venv/bin/python", "/opt/subtitle-ocr/worker.py"]
CMD ["/media"]
