FROM python:3.12-slim
RUN pip install --no-cache-dir numpy
WORKDIR /app
COPY common/ /app/common/
COPY web-service/server.py /app/server.py
ENV PYTHONUNBUFFERED=1
CMD ["python", "/app/server.py"]
