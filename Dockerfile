FROM python:3.12.10-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY runtime /app/runtime
COPY baf /app/baf
RUN mkdir /traces && chown 1000:1000 /traces
USER 1000:1000
EXPOSE 8000
