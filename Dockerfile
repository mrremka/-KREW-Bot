FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN groupadd -g 10001 krew && useradd -u 10001 -g krew -M -s /usr/sbin/nologin krew
COPY --chown=krew:krew . /app
RUN mkdir -p /app/data /app/logs /app/backups && chown -R krew:krew /app/data /app/logs /app/backups
USER krew
EXPOSE 8090
CMD ["python", "main.py"]
