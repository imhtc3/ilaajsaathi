FROM python:3.12-slim
WORKDIR /srv
ENV PYTHONUNBUFFERED=1 PORT=8000 ILAAJ_OUT_DIR=/tmp/ilaaj
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health')" || exit 1
CMD ["python", "-m", "app.server"]
