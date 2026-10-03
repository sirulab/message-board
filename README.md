# 圖文留言板 POC (AWS S3 + CloudFront + RDS + Docker + uv)

極簡版圖文留言板，使用者可以發送文字並上傳圖片，圖片存放於 **AWS S3**，透過 **AWS CloudFront** CDN 進行加速分發，留言資料儲存在 **AWS RDS (MySQL)** 資料庫，並支援使用 **Docker** 與 **uv** 進行快速建置與部署。

---

## 專案結構

```text
.
├── home.html           # 前端留言板頁面 (原生 HTML / JS)
├── style.css           # 極簡樣式表
├── main.py             # FastAPI 後端 API (處理 S3 上傳、RDS 存取與靜態頁面)
├── requirements.txt    # Python 依賴清單
├── Dockerfile          # 使用 uv 的高效容器建置檔
├── docker-compose.yml  # Docker Compose 一鍵啟動檔
├── .dockerignore
├── .env.example        # 環境變數設定範例
└── .env                # 本地/環境變數檔 (請填入個人 AWS 資訊)
```

---

## AWS 服務設定指引

### 1. AWS S3 儲存貯體
1. 進入 AWS S3 主控台，建立一個 Bucket（例如：`my-board-bucket`）。
2. 在「區塊公開存取」設定中，如果透過 CloudFront OAC 存取，可保持封鎖公開存取；若是直接透過 CloudFront 讀取，請確保 CloudFront 有權限存取該 S3 Bucket。

### 2. AWS CloudFront CDN
1. 進入 CloudFront 主控台，點擊 **Create distribution**。
2. **Origin domain** 選擇剛建立的 S3 Bucket。
3. 建立完成後，複製分配的網域名稱（Domain name），例如：`d111111abcdef8.cloudfront.net`。
4. 圖片 URL 將透過此 CDN 網址提供，大幅降低 S3 流量成本並加速圖片載入。

### 3. AWS RDS (MySQL)
1. 進入 RDS 主控台，建立 MySQL 資料庫實例。
2. 記下 **Endpoint（端點）**、**Port (3306)**、**使用者名稱**、**密碼** 與 **初始資料庫名稱**（例如：`message_board`）。
3. 檢查 RDS 所在的 **安全群組 (Security Group)**，確保入站規則 (Inbound Rule) 允許你的主機 / EC2 連線至 3306 埠。
4. *系統啟動時會自動建立 `messages` 資料表，不需手動執行 SQL 建表。*

---

## 設定檔 (.env)

請在專案根目錄確認或編輯 `.env`：

```env
# AWS S3 設定
AWS_ACCESS_KEY_ID=AKIAXXXXXXXXXXXXXXXX
AWS_SECRET_ACCESS_KEY=your_secret_access_key
AWS_REGION=ap-northeast-1
S3_BUCKET_NAME=my-board-bucket

# AWS CloudFront CDN 設定 (不需加 https://)
CLOUDFRONT_DOMAIN=d111111abcdef8.cloudfront.net

# AWS RDS MySQL 資料庫設定
DB_HOST=mydb.xxxxxx.ap-northeast-1.rds.amazonaws.com
DB_PORT=3306
DB_USER=admin
DB_PASSWORD=your_password
DB_NAME=message_board
```

---

## 部署與執行方式

### 方式一：使用 Docker 部署 (推薦)

#### 1. 使用 Docker Compose 一鍵啟動：
```bash
docker compose up -d --build
```

#### 2. 或手動 Build & Run：
```bash
# 建置 Docker 映像檔 (使用 uv 加速建置)
docker build -t message-board .

# 啟動容器
docker run -d -p 8000:8000 --env-file .env --name message-board-app message-board
```

啟動後，使用瀏覽器開啟：`http://localhost:8000`

---

### 方式二：本地使用 `uv` 執行

若本機有安裝 Python 與 `uv`：

```bash
# 1. 建立虛擬環境
uv venv .venv

# 2. 啟用虛擬環境
# Windows:
.venv\Scripts\activate
# Linux / macOS:
source .venv/bin/activate

# 3. 安裝依賴
uv pip install -r requirements.txt

# 4. 啟動伺服器
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

---

## 功能說明

- **GET `/`**：提供極簡留言板首頁。
- **GET `/api/posts`**：從 RDS 讀取所有留言（文字、CloudFront 圖片網址、時間戳記），依時間倒序排列。
- **POST `/api/posts`**：
  - 接收表單文字與圖片檔案。
  - 自動以 UUID 生成不重複檔名並將圖片上傳至 AWS S3。
  - 將 S3 檔案轉換為 CloudFront CDN 網址。
  - 將留言文字與 CDN 圖片網址寫入 AWS RDS MySQL。
  - 前端收到回應後自動刷新留言列表。
