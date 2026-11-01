FROM python:3.15.0-slim-bookworm@sha256:0e019bbdfb5d9874cb2389f1c2884b64aa2ac97c99960b5bc521cef978c0617d

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
