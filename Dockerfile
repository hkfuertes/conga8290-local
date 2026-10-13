FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt
COPY conga8290/ ./conga8290/
COPY recover_key.py cecotec_conga8290_vacuum.yaml ./

# Offline-only test stage. No account, APK, robot or secrets in the build.
FROM base AS tests
COPY requirements-dev.txt ./
RUN python -m pip install --no-cache-dir -r requirements-dev.txt
COPY tests/ ./tests/
RUN python -m unittest discover -s tests -p 'test_*.py'

FROM base AS runtime
# Bind mounts must be pre-created as 0700 and owned by the runtime UID.
USER 10001:10001
ENTRYPOINT ["python", "recover_key.py"]
