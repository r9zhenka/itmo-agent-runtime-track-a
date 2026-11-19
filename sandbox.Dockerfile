FROM python:3.12.10-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY runtime/file_tool.py /opt/file_tool.py
COPY runtime/code_worker.py /opt/code_worker.py
WORKDIR /work
USER 1000:1000
CMD ["python", "-c", "print('Sandbox image ready')"]
