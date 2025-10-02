FROM python:3.12-slim
WORKDIR /app

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt && pip install gunicorn gevent
COPY . .
ENV PORT=8090
EXPOSE 8090
CMD ["gunicorn","-w","4","-k","gevent","-b","0.0.0.0:8090","oraculoicms_app.wsgi:app"]
