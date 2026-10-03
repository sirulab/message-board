import os
import uuid
import shutil
import mimetypes
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, UploadFile, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
import boto3
from botocore.exceptions import ClientError
import pymysql

load_dotenv()

# 本地目錄設定
UPLOAD_DIR = os.path.join("static", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# AWS S3 & CloudFront Configuration
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_REGION = os.getenv("AWS_REGION", "ap-northeast-1")
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")
CLOUDFRONT_DOMAIN = os.getenv("CLOUDFRONT_DOMAIN")

# AWS RDS MySQL Configuration (若留空則自動使用本地 SQLite messages.db)
DB_HOST = os.getenv("DB_HOST", "")
DB_PORT = int(os.getenv("DB_PORT", 3306))
DB_USER = os.getenv("DB_USER", "")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = os.getenv("DB_NAME", "message_board")

USE_SQLITE = not DB_HOST or DB_HOST.lower() in ("sqlite", "none", "local")
USE_LOCAL_STORAGE = not S3_BUCKET_NAME or os.getenv("STORAGE_TYPE") == "local"

# S3 Client 初始化 (僅在非本地儲存時使用)
s3_client = None
if not USE_LOCAL_STORAGE:
    s3_kwargs = {"region_name": AWS_REGION}
    if AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY:
        s3_kwargs["aws_access_key_id"] = AWS_ACCESS_KEY_ID
        s3_kwargs["aws_secret_access_key"] = AWS_SECRET_ACCESS_KEY
    s3_client = boto3.client("s3", **s3_kwargs)


def get_db_connection():
    """建立資料庫連線 (支援 RDS MySQL 或 本地 SQLite)"""
    if USE_SQLITE:
        import sqlite3
        conn = sqlite3.connect("messages.db")
        conn.row_factory = sqlite3.Row
        return conn
    return pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
    )


def init_db():
    """初始化資料庫與資料表"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        if USE_SQLITE:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    text TEXT NOT NULL,
                    image_url TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            conn.commit()
            print("【模式】已啟用本地測試：SQLite (messages.db)")
        else:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    text TEXT NOT NULL,
                    image_url VARCHAR(1024) NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
                """
            )
            print("【模式】已連線 AWS RDS MySQL")
        conn.close()
    except Exception as e:
        print(f"資料庫初始化提示: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    if USE_LOCAL_STORAGE:
        print("【模式】未設定 S3，已啟用本地圖片儲存 (static/uploads/)")
    else:
        print(f"【模式】已啟用 AWS S3 儲存: {S3_BUCKET_NAME}")
    yield


app = FastAPI(title="圖文留言板", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def read_root():
    return FileResponse("home.html")


@app.get("/style.css")
def get_css():
    return FileResponse("style.css", media_type="text/css")


@app.get("/api/posts")
def get_posts():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, text, image_url, created_at FROM messages ORDER BY id DESC")
        rows = cursor.fetchall()
        conn.close()

        posts = [
            {
                "id": row["id"],
                "text": row["text"],
                "imageUrl": row["image_url"],
                "createdAt": str(row["created_at"]),
            }
            for row in rows
        ]
        return posts
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"無法取得留言列表: {str(e)}",
        )


@app.post("/api/posts")
async def create_post(text: str = Form(...), image: UploadFile = File(...)):
    if not text.strip():
        raise HTTPException(status_code=400, detail="留言文字不能為空")

    if not image or not image.filename:
        raise HTTPException(status_code=400, detail="請選擇圖片檔案")

    file_ext = os.path.splitext(image.filename)[1].lower() or ".jpg"
    filename = f"{uuid.uuid4().hex}{file_ext}"

    # 1. 圖片儲存：本地模式 vs AWS S3
    if USE_LOCAL_STORAGE:
        file_path = os.path.join(UPLOAD_DIR, filename)
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(image.file, buffer)
        image_url = f"/static/uploads/{filename}"
    else:
        s3_key = f"uploads/{filename}"
        content_type = image.content_type
        if not content_type or content_type == "application/octet-stream":
            content_type = mimetypes.guess_type(image.filename)[0] or "image/jpeg"

        try:
            s3_client.upload_fileobj(
                image.file,
                S3_BUCKET_NAME,
                s3_key,
                ExtraArgs={"ContentType": content_type},
            )
        except ClientError as e:
            raise HTTPException(status_code=500, detail=f"S3 圖片上傳失敗: {str(e)}")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"AWS 連線錯誤: {str(e)}")

        if CLOUDFRONT_DOMAIN:
            cf_domain = CLOUDFRONT_DOMAIN.strip().replace("https://", "").replace("http://", "").rstrip("/")
            image_url = f"https://{cf_domain}/{s3_key}"
        else:
            image_url = f"https://{S3_BUCKET_NAME}.s3.{AWS_REGION}.amazonaws.com/{s3_key}"

    # 2. 寫入資料庫
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        if USE_SQLITE:
            sql = "INSERT INTO messages (text, image_url) VALUES (?, ?)"
            cursor.execute(sql, (text.strip(), image_url))
            conn.commit()
            new_id = cursor.lastrowid
        else:
            sql = "INSERT INTO messages (text, image_url) VALUES (%s, %s)"
            cursor.execute(sql, (text.strip(), image_url))
            new_id = cursor.lastrowid
        conn.close()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"資料庫寫入失敗: {str(e)}")

    return {
        "status": "success",
        "post": {
            "id": new_id,
            "text": text.strip(),
            "imageUrl": image_url,
        },
    }