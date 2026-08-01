FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ONE_CRM_NO_BROWSER=1

WORKDIR /app

COPY . /app

RUN mkdir -p /app/data /app/logs

EXPOSE 8000

CMD ["python", "one_crm_server.py"]
