import os, time, shutil, traceback, asyncio, re, io, random
import pandas as pd
from fastapi import FastAPI, HTTPException, BackgroundTasks, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import core.sprite_controller as sprite_controller
import gc
from core.profile_manager import load_profile
import torch
import requests

# Módulos propios
from modules.voice_engine import generate_audio, get_word_timestamps
from modules.asset_manager import AssetManager
from modules.processor import extract_keywords
from modules.video_engine import VideoEngine

app = FastAPI(title="AI Shorts API")

# --- CONFIGURACIÓN Y RUTAS ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
JOBS_DIR = os.path.join(ASSETS_DIR, "jobs")
DOCS_OUTPUT_BASE = os.path.abspath(r'C:\Users\nicol\Desktop\n8n\storage\1ClickShorts\videos')
API_URL = "http://127.0.0.1:8000"

# ----- N8N CONFIG -----
N8N_WEBHOOK_TRIGGER = "http://localhost:5678/webhook-test/3339af6c-9574-4752-835c-b85838f04c0c" 
N8N_WEBHOOK_VIDEO_READY = "http://localhost:5678/webhook/3339af6c-9574-4752-835c-b85838f04c0c" 


# Asegurar directorios base
for d in [ASSETS_DIR, JOBS_DIR, DOCS_OUTPUT_BASE]:
    os.makedirs(d, exist_ok=True)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# Estado global
export_progress = {"status": "esperando", "percent": 0, "final_url": None}

# --- UTILIDADES ---
def sanitize_filename(name: str, fallback: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9_\-]+", "_", str(name or "").strip())
    return name.strip("_") or fallback

def notify_n8n(job_id, final_path, title, profile):
    """Envía la información del video finalizado a n8n."""
    payload = {
        "job_id": job_id,
        "status": "completed",
        "video_url": f"http://localhost:8000/assets/videos/{os.path.basename(final_path)}", 
        "file_path": os.path.abspath(final_path), 
        "output_directory": os.path.dirname(os.path.abspath(final_path)),
        "filename": os.path.basename(final_path),
        "title": title,
        "profile": profile,
        "event": "video_ready",
        "timestamp": time.time()
    }
    
    try:
        # Usamos la URL de VIDEO_READY que definiste en la configuración
        response = requests.post(N8N_WEBHOOK_VIDEO_READY, json=payload, timeout=10)
        print(f"📡 Datos enviados a n8n: {response.status_code}")
    except Exception as e:
        print(f"⚠️ Error al notificar a n8n: {e}")

def group_timestamps(raw_timestamps):
    segments, temp_words = [], []
    for i, w in enumerate(raw_timestamps):
        temp_words.append(w)
        is_last = i == len(raw_timestamps) - 1
        gap = False if is_last else (raw_timestamps[i+1]["start"] - w["end"]) > 0.3
        has_punct = any(p in w["raw_word"] for p in {".", "!", "?", ","})
        duration = temp_words[-1]["end"] - temp_words[0]["start"]

        if gap or (has_punct and duration > 1.2) or duration > 3.5 or is_last:
            segments.append({
                "phrase": " ".join([x["word"] for x in temp_words]),
                "start": temp_words[0]["start"],
                "end": temp_words[-1]["end"],
                "words": list(temp_words)
            })
            temp_words = []
    return segments

# --- LÓGICA DE PROCESAMIENTO ---

async def process_row(text, profile, title, keywords_override, job_id, job_path, output_dir, layout_override=None):
    success = False
    try:
        print(f"\n🚀 Procesando: {title} | Job ID: {job_id}")
        sprite_controller._last_pose = None 
        gc.collect()

        prof_data = load_profile(profile)
        voice_model = prof_data.get("voice_model", "es_ES-sharvard-medium")
        el_style = prof_data.get("elevenlabs_style", {})
        
        audio_dir = os.path.join(job_path, "audio")
        os.makedirs(audio_dir, exist_ok=True)
        voice_path = os.path.join(audio_dir, "voice.wav")

        audio_path = await generate_audio(text, voice=voice_model, save_path=voice_path, elevenlabs_style=el_style)
        
        raw_ts = get_word_timestamps(audio_path, job_path, text)
        segments = group_timestamps(raw_ts)
        manager = AssetManager(profile_name=profile, job_id=job_id)

        kw_override = (keywords_override or "").strip().replace(";", ",")
        clips = []
        for j, seg in enumerate(segments):
            duracion_segmento = seg["end"] - seg["start"] + 0.5
            kw = kw_override if kw_override else extract_keywords(seg["phrase"])
            print(kw)
            options = manager.search_stock_videos(kw)
            if options:
                chosen = random.choice(options[:5])
                p = manager.download_from_url(chosen["download_link"], f"clip_{j}", job_path, duration=duracion_segmento)
                if p: clips.append(os.path.abspath(p))

        out_temp = os.path.join(job_path, "output", "final_render.mp4")
        os.makedirs(os.path.dirname(out_temp), exist_ok=True)

        engine = VideoEngine(output_path=out_temp)
        engine.assemble_video(
            clip_paths=clips, 
            audio_path=os.path.abspath(audio_path), 
            segments=segments, 
            profile_name=profile, 
            job_path=job_path,
            layout_mode=layout_override
        )

        safe_title = sanitize_filename(title, fallback=f"video_{job_id}")
        final_path = os.path.join(output_dir, f"{safe_title}.mp4")
        os.makedirs(output_dir, exist_ok=True)
        
        shutil.copy2(out_temp, final_path)
        print(f"✨ VIDEO LISTO: {final_path}")
        
        success = True
        
        # --- AVISO A N8N (AUTOMÁTICO) ---
        notify_n8n(job_id, final_path, title, profile)
            
        return final_path

    except Exception as e:
        print(f"❌ Error: {str(e)}")
        traceback.print_exc()
        raise e
    finally:
        sprite_controller._last_pose = None
        gc.collect()
        if torch.cuda.is_available(): torch.cuda.empty_cache()
        if success:
            time.sleep(2)
            shutil.rmtree(job_path, ignore_errors=True)

# --- ENDPOINTS ---

@app.post("/export")
async def export_video(request: dict, background_tasks: BackgroundTasks):
    job_id = request["job_id"]
    selections = request["selections"]
    segments = request["timestamps"]
    profile = request.get("profile")
    preset_from_front = request.get("preset")
    position_from_front = request.get("position")

    async def run_export():
        success = False
        job_path = os.path.join(JOBS_DIR, job_id)
        try:
            export_progress.update({"status": "Descargando clips...", "percent": 10})
            manager = AssetManager(profile_name=profile)
            clips = [manager.download_from_url(url, f"clip_{i}", job_path, duration=(segments[int(idx)]["end"]-segments[int(idx)]["start"]+0.2)) 
                     for i, (idx, url) in enumerate(selections.items())]
            clips = [c for c in clips if c]

            export_progress.update({"status": "Renderizando...", "percent": 50})
            out_temp = os.path.join(job_path, "output", "final.mp4")
            os.makedirs(os.path.dirname(out_temp), exist_ok=True)

            await asyncio.to_thread(
                VideoEngine(output_path=out_temp).assemble_video,
                clip_paths=clips, audio_path=os.path.join(job_path, "audio", "voice.wav"), 
                segments=segments, profile_name=profile, job_path=job_path,
                preset_from_front=preset_from_front, position_from_front=position_from_front
            )

            final_path = os.path.join(DOCS_OUTPUT_BASE, "Manual", f"video_{job_id}.mp4")
            os.makedirs(os.path.dirname(final_path), exist_ok=True)
            shutil.copy2(out_temp, final_path)
            
            # --- AVISO A N8N (MANUAL) ---
            notify_n8n(job_id, final_path, f"Manual_{job_id}", profile)

            export_progress.update({"status": "¡Completado!", "percent": 100, "final_url": f"file://{final_path}"})
            success = True
        except Exception as e:
            export_progress.update({"status": f"Error: {str(e)}", "percent": 0})
        finally:
            if success:
                time.sleep(1.5)
                shutil.rmtree(job_path, ignore_errors=True)

    background_tasks.add_task(run_export)
    return {"message": "Exportación iniciada"}

@app.post("/batch")
async def batch_process(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    content = await file.read()
    df = pd.read_csv(io.BytesIO(content), sep=None, engine='python').rename(columns=lambda x: x.strip().lower())
    df = df.dropna(subset=['texto']) 
    
    async def run_batch():
        for i, row in df.iterrows():
            job_id = f"batch_{int(time.time())}_{i}"
            try:
                await process_row(
                    text=str(row.get("texto")).strip(), profile=row.get("profile"), 
                    title=row.get("titulo"), keywords_override=row.get("keywords"), 
                    job_id=job_id, job_path=os.path.join(JOBS_DIR, job_id), 
                    output_dir=os.path.join(DOCS_OUTPUT_BASE, "Batch"),
                    layout_override=str(row.get("layout")).strip() if pd.notna(row.get("layout")) else None
                )
            except: continue
    background_tasks.add_task(run_batch)
    return {"message": "Batch iniciado", "rows": len(df)}

@app.post("/process-single")
async def process_single(request: dict, background_tasks: BackgroundTasks):
    job_id = f"n8n_{int(time.time())}"
    
    # 1. Construimos la ruta que tendrá el video al finalizar
    safe_title = sanitize_filename(request.get("titulo"), fallback=f"video_{job_id}")
    # output_dir = os.path.join(DOCS_OUTPUT_BASE, "n8n_Automation")
    final_expected_path = os.path.abspath(os.path.join(DOCS_OUTPUT_BASE, f"{safe_title}.mp4"))

    # 2. Lanzamos la tarea
    background_tasks.add_task(
        process_row, 
        text=request.get("texto"), 
        profile=request.get("profile"),
        title=request.get("titulo"), 
        keywords_override=request.get("keywords"),
        job_id=job_id, 
        job_path=os.path.join(JOBS_DIR, job_id),
        output_dir=DOCS_OUTPUT_BASE,
        layout_override=request.get("layout")
    )
    
    # 3. Devolvemos la ruta inmediatamente
    return {
        "status": "Procesamiento iniciado", 
        "job_id": job_id,
        "final_path": final_expected_path  # <--- Aquí tienes la ruta
    }

@app.get("/export-status")
async def get_status(): return export_progress

# --- EVENTO DE ARRANQUE ---

@app.on_event("startup")
async def on_startup():
    """Se ejecuta cuando la API está lista."""
    print("API levantada y escuchando en el puerto 8000")
    
    # Payload para avisar que el sistema está online
    startup_payload = {
        "event": "system_online",
        "status": "ready",
        "timestamp": time.time(),
        "api_url": API_URL
    }

    try:
        # Usamos asyncio.to_thread para no bloquear el inicio si la red es lenta
        # Reutilizamos la URL de n8n que ya tienes definida
        await asyncio.sleep(1) # Espera un segundo para asegurar que el socket está abierto
        response = requests.post(N8N_WEBHOOK_TRIGGER, json=startup_payload, timeout=5)
        print(f"📡 Señal de vida enviada a n8n: {response.status_code}")
    except Exception as e:
        print(f"⚠️ No se pudo avisar a n8n del inicio: {e}")

app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="assets")
app.mount("/final_videos", StaticFiles(directory=DOCS_OUTPUT_BASE), name="final_videos")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)