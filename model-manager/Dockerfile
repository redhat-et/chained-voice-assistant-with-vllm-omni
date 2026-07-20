FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir kubernetes
COPY model-manager.py .
USER 1001
ENTRYPOINT ["python", "model-manager.py"]
