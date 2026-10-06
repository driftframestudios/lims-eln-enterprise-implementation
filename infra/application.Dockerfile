FROM python:3.12.15-slim-bookworm@sha256:54c85f3c47607a77f32adec749d3c81d1348bf25833671f512b26a9b6d778cb3

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /opt/workbench
COPY requirements.txt ./requirements.txt
RUN python -m pip install --no-cache-dir --require-hashes --only-binary=:all: -r requirements.txt
COPY wheels/ ./wheels/
RUN python -m pip install --no-cache-dir --no-deps wheels/*.whl \
    && rm -r wheels
COPY build-inputs.json ./build-inputs.json
USER 10001:10001
EXPOSE 8000
ENTRYPOINT ["python", "-m", "uvicorn", "lims_eln_implementation.workbench.runtime:create_configured_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
