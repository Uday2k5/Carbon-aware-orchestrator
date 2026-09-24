FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY cao ./cao
COPY config ./config
RUN pip install --no-cache-dir .[k8s]
ENTRYPOINT ["cao"]
