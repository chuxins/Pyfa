# pyfa web
#
# Multi-stage: build the Vue front end with Node, then run the API with the
# Python dependencies. wxPython is deliberately *not* installed -- the server
# runs the engine headlessly through pyfa_compat/.

FROM node:22-slim AS frontend
WORKDIR /build
COPY web/frontend/package.json web/frontend/package-lock.json* ./
RUN npm install --no-fund --no-audit
COPY web/frontend/ ./
RUN npm run build


FROM python:3.14-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYFA_WEB_DATA_DIR=/data \
    PYFA_WEB_HOST=0.0.0.0 \
    PYFA_WEB_PORT=8080

WORKDIR /app

# Runtime dependencies only; see pyproject.toml for the full list
RUN pip install --no-cache-dir \
    "logbook==1.9.2" \
    "numpy==2.5.1" \
    "matplotlib==3.11.1" \
    "python-dateutil==2.9.0.post0" \
    "requests==2.34.2" \
    "sqlalchemy==2.0.51" \
    "cryptography==50.0.0" \
    "markdown2==2.5.5" \
    "packaging==26.2" \
    "roman==5.2" \
    "beautifulsoup4==4.15.0" \
    "pyyaml==6.0.3" \
    "python-jose==3.5.0" \
    "requests-cache==1.3.3" \
    "fastapi==0.141.1" \
    "uvicorn[standard]==0.54.0" \
    "itsdangerous==2.2.0"

COPY eos/ ./eos/
COPY graphs/ ./graphs/
COPY service/ ./service/
COPY utils/ ./utils/
COPY locale/ ./locale/
COPY staticdata/ ./staticdata/
COPY imgs/ ./imgs/
COPY gui/ ./gui/
COPY pyfa_compat/ ./pyfa_compat/
COPY web/ ./web/
COPY config.py db_update.py version.yml ./

# The front end build replaces whatever was committed under web/static
COPY --from=frontend /static ./web/static

VOLUME ["/data"]
EXPOSE 8080

# eve.db is built from staticdata/ on first start, which takes a minute
HEALTHCHECK --interval=30s --timeout=5s --start-period=180s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/api/meta', timeout=4).status == 200 else 1)"

CMD ["python", "-m", "web"]
