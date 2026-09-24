FROM python:3.12-slim
RUN pip install --no-cache-dir numpy
WORKDIR /app
COPY common/ /app/common/
COPY batch/process.py /app/process.py
ENV PYTHONUNBUFFERED=1
CMD ["python", "/app/process.py"]
