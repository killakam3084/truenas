FROM tentacule/pgstosrt@sha256:3501a68223c06bf779c94c4efd68e5214a9bc506e55cc1f77291c827bc266597

USER root
RUN apt-get update \
    && apt-get install --no-install-recommends -y python3 python3-venv mkvtoolnix curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/subtitle-ocr
COPY requirements.txt ./
RUN python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt \
    && mkdir tessdata \
    && curl --fail --location --output tessdata/eng.traineddata https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/main/eng.traineddata \
    && echo '7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2  tessdata/eng.traineddata' | sha256sum -c -
COPY worker.py test_worker.py ./
RUN /opt/venv/bin/python -m unittest -v
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 OMP_THREAD_LIMIT=2 DOTNET_CLI_TELEMETRY_OPTOUT=1
USER 950:950
ENTRYPOINT ["/opt/venv/bin/python", "/opt/subtitle-ocr/worker.py"]
CMD ["/media"]