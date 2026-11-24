FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install . \
    && useradd --system --uid 10001 --no-create-home etl

USER 10001
ENTRYPOINT ["python", "-m", "sig_etl"]
CMD ["run"]
