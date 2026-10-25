FROM python:3.13-slim
WORKDIR /app
COPY . /app
ENV PYTHONUNBUFFERED=1 PROOFCHECK_DB=/data/proofcheck.sqlite3
RUN mkdir -p /data && useradd -r -u 10001 appuser && chown 10001:10001 /data
USER 10001
EXPOSE 8765
CMD ["python", "server.py", "--mode", "web", "--port", "8765", "--no-browser"]
