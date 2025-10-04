FROM python:3.12-slim
ENV FLASK_APP=oraculoicms_app.wsgi:create_app
ARG BUILD_REV=dev
LABEL org.opencontainers.image.revision=$BUILD_REV
ARG APP_HASH
ENV APP_HASH=${APP_HASH}
WORKDIR /app

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt && pip install gunicorn gevent

COPY . .
ENV PORT=8090
EXPOSE 8090
CMD ["gunicorn","-w","4","-k","gevent","-b","0.0.0.0:8090","oraculoicms_app.wsgi:app"]
