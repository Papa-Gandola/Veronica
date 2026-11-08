FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=UTC

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY veronica_brain ./veronica_brain

# Состояние (SQLite-дневник) и общая папка с freqtrade монтируются снаружи.
VOLUME ["/app/data", "/freqtrade/user_data"]

ENTRYPOINT ["python", "-m", "veronica_brain"]
CMD ["run"]
