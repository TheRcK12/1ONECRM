FROM python:3.11-slim-bookworm

LABEL org.opencontainers.image.title="ONE CRM" \
      org.opencontainers.image.description="ONE CRM multi-perfil preparado para Railway" \
      org.opencontainers.image.version="2.6.8-beta.1"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONHASHSEED=random \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    ONE_CRM_NO_BROWSER=1 \
    ONE_CRM_RUNTIME_USER=onecrm \
    ONE_CRM_RUNTIME_UID=10001 \
    ONE_CRM_RUNTIME_GID=10001

WORKDIR /app

RUN groupadd --gid 10001 onecrm \
    && useradd --uid 10001 --gid 10001 --create-home --home-dir /home/onecrm --shell /usr/sbin/nologin onecrm

COPY requirements.txt /app/requirements.txt
RUN python -m pip install --no-cache-dir -r /app/requirements.txt

COPY --chown=10001:10001 one_crm_server.py one_crm_ai.py one_crm_profiles.py one_crm_productivity.py railway_entrypoint.py /app/
COPY --chown=10001:10001 config.json version.json /app/
COPY --chown=10001:10001 static /app/static

# /app/data is created inside the image and may later be replaced by the Railway Volume.
# Do not COPY a placeholder from the repository: Git/ZIP workflows can omit dotfiles.
RUN mkdir -p /app/data/backups /app/data/logs \
    && chown -R 10001:10001 /app \
    && python -m compileall -q /app

EXPOSE 8000
STOPSIGNAL SIGTERM

# O entrypoint inicia como root somente para ajustar a permissão do Volume,
# que o Railway monta como root. Em seguida ele abandona privilégios e executa
# o servidor como UID 10001.
ENTRYPOINT ["python", "/app/railway_entrypoint.py"]
CMD ["python", "/app/one_crm_server.py"]
