FROM python:3.11-slim

# 從官方 uv 映像檔複製 uv，加速套件安裝
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# 使用 uv 安裝依賴套件至系統環境
COPY requirements.txt .
RUN uv pip install --system --no-cache -r requirements.txt

# 複製應用程式程式碼
COPY . .

EXPOSE 8000

# 啟動 FastAPI 服務
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
