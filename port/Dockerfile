FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir fastapi uvicorn
COPY . /app/port
RUN touch /app/port/__init__.py
EXPOSE 8080
CMD ["uvicorn", "port.app:app", "--host", "0.0.0.0", "--port", "8080"]
