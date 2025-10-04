FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=on


ENV FLASK_APP=oraculoicms_app.wsgi:create_app
ARG BUILD_REV=dev
LABEL org.opencontainers.image.revision=$BUILD_REV
ARG APP_HASH
ENV APP_HASH=${APP_HASH}
WORKDIR /app


COPY requirements.txt /tmp/requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip && \
    pip install --no-warn-script-location -r /tmp/requirements.txt

COPY . .
ENV PORT=8090
EXPOSE 8090
CMD ["gunicorn","-w","4","-k","gevent","-b","0.0.0.0:8090","oraculoicms_app.wsgi:app"]
