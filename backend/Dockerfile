FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
# Pre-install torch from CPU-only wheel index. Avoids ~5 GB of NVIDIA CUDA
# libraries that easyocr would otherwise pull in (we always run with gpu=False).
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch torchvision
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

HEALTHCHECK --interval=60s --timeout=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')"

RUN adduser --disabled-password --gecos '' appuser
USER appuser

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
