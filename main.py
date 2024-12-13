from fastapi import FastAPI, Request, WebSocket, Response
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, StreamingResponse
import yt_dlp
import asyncio
import json
from pathlib import Path
from datetime import datetime
import io

app = FastAPI()

# 获取项目根目录的绝对路径
ROOT_DIR = Path(__file__).resolve().parent

# 修改静态文件和模板配置
app.mount("/static", StaticFiles(directory=str(ROOT_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(ROOT_DIR / "templates"))

# 使用内存存储视频信息
videos_info = []
videos_data = {}  # 用于存储视频二进制数据

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
        'outtmpl': '-'  # 输出到内存
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            video_info = {
                "title": info["title"],
                "duration": info["duration"],
                "author": info["uploader"],
                "description": info["description"],
                "file_size": info.get("filesize", 0),
                "video_id": info["id"],
                "download_date": datetime.now().isoformat()
            }
            
            # 将视频信息添加到内存列表
            videos_info.append(video_info)
            
            return video_info
    except Exception as e:
        await websocket.send_json({"status": "error", "message": str(e)})
        return None

@app.get("/")
async def home(request: Request):
    return templates.TemplateResponse(
        "index.html", 
        {"request": request, "videos": videos_info}
    )

@app.get("/video/{video_id}")
async def serve_video(video_id: str):
    video_info = next((v for v in videos_info if v["video_id"] == video_id), None)
    if not video_info:
        return JSONResponse({"error": "Video not found"}, status_code=404)
    
    # 这里需要实现视频流式传输
    # 在实际应用中，你可能需要将视频存储在云存储服务中
    return JSONResponse({"error": "Video streaming not implemented"}, status_code=501)

@app.get("/api/health")
async def health_check():
    return {"status": "ok"}

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