import os
import random
import requests
import subprocess
from concurrent.futures import ThreadPoolExecutor
from deep_translator import GoogleTranslator
import config

class AssetManager:
    def __init__(self, job_id="default", profile_name=None, profile=None):
        self.api_key = getattr(config, "PEXELS_API_KEY", None)
        self.used_video_ids = set()
        if not self.api_key or self.api_key.strip() in ("", "###"):
            raise ValueError("PEXELS_API_KEY no configurada correctamente en config.py")

        self.session = requests.Session()
        self.session.headers.update({"Authorization": self.api_key})
        self.base_url = "https://api.pexels.com/videos/search"
        self.translator = GoogleTranslator(source="es", target="en")
        self.job_id = job_id
        self.profile_name = (profile_name or "default").strip().lower()

        # Configuración de recorte
        self.target_w = 720
        self.target_h = 720

        self.profile_styles = {
            "default": ["cinematic ultra-high quality", "4k moody lighting"],
            "finanzas": ["corporate modern office", "business meeting cinematic", "trading desk"],
            "amor": ["warm intimate lighting", "romantic cinematic aesthetic"],
        }

        self.profile_fallback_query = {
            "default": "nature cinematic",
            "finanzas": "corporate office cinematic",
            "amor": "cozy lifestyle cinematic",
        }

    def _pick_style(self):
        estilos = self.profile_styles.get(self.profile_name, self.profile_styles["default"])
        return random.choice(estilos)

    def search_stock_videos(self, keyword, per_page=10):
        """Busca videos en Pexels y devuelve los links de descarga."""
        estilo = self._pick_style()
        search_query_raw = f"{keyword} {estilo}"

        try:
            search_query = self.translator.translate(search_query_raw)
        except:
            search_query = search_query_raw

        params = {
            "query": search_query,
            "per_page": per_page,
            "orientation": "portrait",
            "size": "medium",
        }

        try:
            response = self.session.get(self.base_url, params=params, timeout=10)
            data = response.json()
            videos = data.get("videos", [])

            if not videos:
                params["query"] = self.profile_fallback_query.get(self.profile_name, "nature cinematic")
                response = self.session.get(self.base_url, params=params, timeout=10)
                videos = response.json().get("videos", [])
        except Exception as e:
            print(f"Error en Pexels API: {e}")
            videos = []

        options = []
        for video in videos:
            video_id = video.get("id")
            if video_id in self.used_video_ids: continue
            files = video.get("video_files", [])
            best_file = next(
                (f for f in files if f.get("width", 0) <= 1080 and f.get("height", 0) > f.get("width", 0)),
                files[0] if files else None
            )

            if best_file:
                options.append({
                    "id": video_id, # Guardamos el ID
                    "preview_img": video.get("image"),
                    "download_link": best_file["link"],
                })
        return options

    def _process_video_ffmpeg(self, input_path, output_path):
        """
        Filtro inteligente: Escala el video para que quepa en 720x720 
        y luego lo recorta, evitando el error de 'Invalid size'.
        """
        # Explicación del filtro:
        # 1. scale: escala el video para que el lado más corto sea al menos 720
        # 2. crop: corta el cuadrado central de 720x720
        # 3. setsar: corrige el aspect ratio para evitar deformaciones
        smart_filter = (
            f"scale='if(lt(iw,ih),720,-1)':'if(lt(iw,ih),-1,720)',"
            f"crop={self.target_w}:{self.target_h},setsar=1,fps=24"
        )
        
        cmd = [
            "ffmpeg", "-y",
            "-i", input_path,
            "-vf", smart_filter,
            "-c:v", "h264_nvenc",
            "-pix_fmt", "yuv420p",
            "-preset", "p1",
            "-tune", "ll",
            "-an", "-ss", "00:00:00", "-t", "10",
            output_path
        ]
        
        try:
            # Ejecutamos sin capturar output para ver el progreso real
            subprocess.run(cmd, check=True)
            return True
        except Exception:
            return self._process_video_ffmpeg_cpu(input_path, output_path)

    def _process_video_ffmpeg_cpu(self, input_path, output_path):
        """CPU Fallback con el mismo filtro inteligente"""
        smart_filter = (
            f"scale='if(lt(iw,ih),720,-1)':'if(lt(iw,ih),-1,720)',"
            f"crop={self.target_w}:{self.target_h},setsar=1,fps=24"
        )
        cmd = [
            "ffmpeg", "-y", "-i", input_path,
            "-vf", smart_filter,
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
            "-an", "-ss", "00:00:00", "-t", "10",
            output_path
        ]
        try:
            subprocess.run(cmd, check=True)
            return True
        except: return False

    def _process_video_ffmpeg(self, input_path, output_path, duration=10):
        """Filtro unificado con fallback inteligente"""
        # Aseguramos que la duración sea un string válido para FFmpeg
        duration_str = str(max(1, float(duration)))
        
        smart_filter = (
            f"scale='if(lt(iw,ih),720,-1)':'if(lt(iw,ih),-1,720)',"
            f"crop={self.target_w}:{self.target_h},setsar=1,fps=30" # Subido a 30fps para fluidez
        )
        
        # Intentar GPU
        cmd = [
            "ffmpeg", "-y", "-i", input_path,
            "-vf", smart_filter,
            "-c:v", "h264_nvenc", "-preset", "p1", "-an", 
            "-t", duration_str, output_path
        ]
        
        try:
            subprocess.run(cmd, check=True, capture_output=True)
            return True
        except:
            # Fallback CPU
            cmd[7] = "libx264" # Cambiar codec a CPU
            cmd.insert(8, "-crf")
            cmd.insert(9, "23")
            try:
                subprocess.run(cmd, check=True, capture_output=True)
                return True
            except:
                return False

    # Cambia la firma del método
    def download_from_url(self, url, filename, job_path, duration=10): 
        save_dir = os.path.join(job_path, "clips")
        os.makedirs(save_dir, exist_ok=True)
        
        raw_path = os.path.join(save_dir, f"raw_{filename}.mp4")
        final_path = os.path.join(save_dir, f"{filename}.mp4")

        try:
            with self.session.get(url, stream=True, timeout=30) as r:
                r.raise_for_status()
                with open(raw_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1024 * 1024):
                        f.write(chunk)
            

            success = self._process_video_ffmpeg(raw_path, final_path, duration)
            
            if os.path.exists(raw_path): 
                os.remove(raw_path)
            
            return final_path if success else None
        except Exception as e:
            print(f"Error procesando {filename}: {e}")
            return None

    def download_multiple_clips(self, clips_to_download, job_path):
        results = []
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [
                executor.submit(self.download_from_url, url, fname, job_path) 
                for url, fname in clips_to_download
            ]
            for future in futures:
                res = future.result()
                if res: results.append(res)
        return results