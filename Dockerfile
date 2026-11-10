FROM python:3.10-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY WorkForce/requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt
RUN mkdir -p /app/data

COPY WorkForce/ /app/

EXPOSE 8000

CMD ["sh", "-c", "python manage.py migrate --noinput && python manage.py runserver 0.0.0.0:8000"]
