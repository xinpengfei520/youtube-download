from fastapi import FastAPI, Request, WebSocket
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
import yt_dlp
import asyncio
import json
import os
from pathlib import Path
from datetime import datetime
import boto3
from botocore.exceptions import ClientError

app = FastAPI()

# 获取项目根目录的绝对路径
ROOT_DIR = Path(__file__).resolve().parent

# 修改静态文件和模板配置
app.mount("/static", StaticFiles(directory=str(ROOT_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(ROOT_DIR / "templates"))

# 创建下载目录
DOWNLOAD_DIR = ROOT_DIR / "downloads"
DOWNLOAD_DIR.mkdir(exist_ok=True)

# 存储下载任务状态
download_tasks = {}

# 添加S3支持
s3_client = boto3.client(
    's3',
    aws_access_key_id='your_access_key',
    aws_secret_access_key='your_secret_key'
)

def get_video_info(url):
    with yt_dlp.YoutubeDL() as ydl:
        try:
            info = ydl.extract_info(url, download=False)
            return {
                "title": info["title"],
                "duration": info["duration"],
                "author": info["uploader"],
                "description": info["description"],
                "thumbnail": info["thumbnail"]
            }
        except Exception as e:
            return {"error": str(e)}

async def download_video(url: str, websocket: WebSocket):
    def progress_hook(d):
        if d['status'] == 'downloading':
            progress = {
                'status': 'downloading',
                'downloaded_bytes': d.get('downloaded_bytes', 0),
                'total_bytes': d.get('total_bytes', 0),
                'speed': d.get('speed', 0),
                'eta': d.get('eta', 0)
            }
            asyncio.create_task(websocket.send_json(progress))
        elif d['status'] == 'finished':
            progress = {'status': 'finished'}
            asyncio.create_task(websocket.send_json(progress))

    ydl_opts = {
        'format': 'best',
        'progress_hooks': [progress_hook],
        'outtmpl': str(DOWNLOAD_DIR / '%(title)s.%(ext)s')
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url)
            video_path = DOWNLOAD_DIR / f"{info['title']}.{info['ext']}"
            
            # 使用本地路径
            video_info = {
                "title": info["title"],
                "duration": info["duration"],
                "author": info["uploader"],
                "description": info["description"],
                "file_size": os.path.getsize(video_path),
                "local_path": str(video_path),  # 改回使用本地路径
                "download_date": datetime.now().isoformat()
            }
            
            # 将视频信息保存到JSON文件
            with open(DOWNLOAD_DIR / "videos.json", "a+") as f:
                json.dump(video_info, f)
                f.write("\n")
                
            return video_info
    except Exception as e:
        await websocket.send_json({"status": "error", "message": str(e)})
        return None

@app.get("/")
async def home(request: Request):
    # 读取已下载的视频列表
    videos = []
    if (DOWNLOAD_DIR / "videos.json").exists():
        with open(DOWNLOAD_DIR / "videos.json", "r") as f:
            for line in f:
                if line.strip():
                    videos.append(json.loads(line))
    
    return templates.TemplateResponse(
        "index.html", 
        {"request": request, "videos": videos}
    )

@app.websocket("/ws/download")
async def websocket_download(websocket: WebSocket):
    await websocket.accept()
    
    try:
        while True:
            url = await websocket.receive_text()
            video_info = await download_video(url, websocket)
            if video_info:
                await websocket.send_json({"status": "complete", "video_info": video_info})
    except Exception as e:
        await websocket.send_json({"status": "error", "message": str(e)})
    finally:
        await websocket.close()

@app.get("/video/{video_name}")
async def serve_video(video_name: str):
    video_path = DOWNLOAD_DIR / video_name
    if video_path.exists():
        return FileResponse(video_path)
    return JSONResponse({"error": "Video not found"}, status_code=404) 