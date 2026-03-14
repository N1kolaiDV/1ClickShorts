import os, subprocess, pysubs2, time, gc, shutil, wave
import movis as mv
from core.profile_manager import load_profile
import core.sprite_controller as sprite_controller

os.environ["OMP_NUM_THREADS"] = "8" 

class VideoEngine:
    def __init__(self, output_path):
        self.output_path = os.path.abspath(output_path)
        self.canvas_size = (1080, 1920) 
        self.temp_dir = os.path.abspath("assets/output")
        os.makedirs(self.temp_dir, exist_ok=True)
        # Cache para evitar recargar imágenes idénticas del disco
        self._sprite_cache = {}

    def _generate_ass(self, segments, profile, override_preset=None, override_margin=None):
        print(f"📝 Generando archivo de subtítulos (.ass)...")
        st_cfg = profile.get("layout", {}).get("subtitles", {})
        selected_preset = override_preset or st_cfg.get("preset_path", "default.ass")
        preset_path = os.path.join("assets", "subtitles", selected_preset)
        
        subs = pysubs2.load(preset_path) if os.path.exists(preset_path) else pysubs2.SSAFile()
        subs.events = [] 
        subs.info["PlayResX"], subs.info["PlayResY"] = 1080, 1920
        
        for style in subs.styles.values():
            style.fontsize = 120 
            style.fontname = "Arial Black"
            style.alignment = 5           
            style.outline = 6
            style.marginv = 0 

        if override_margin:
            for style in subs.styles.values():
                style.marginv = int(override_margin)

        highlight = st_cfg.get("highlight_color", r"&H00FFFF&")
        word_count = 0
        for seg in segments:
            for w in seg.get("words", []):
                start, end = int(w["start"] * 1000), int(w["end"] * 1000)
                tags = r"\fscx0\fscy0\t(0,80,\fscx115\fscy115)\t(80,150,\fscx100\fscy100)"
                text = f"{{{tags}\\1c{highlight}}}{w['word'].upper()}"
                subs.append(pysubs2.SSAEvent(start=start, end=end, text=text))
                word_count += 1
        
        path = os.path.join(self.temp_dir, f"subs_{int(time.time()*1000)}.ass")
        subs.save(path)
        print(f"✅ Subtítulos generados: {word_count} palabras procesadas.")
        return path

    def assemble_video(self, clip_paths, audio_path, segments, profile_name, job_path, 
                        preset_from_front=None, position_from_front=None, layout_mode=None):
        
        print(f"\n🎬 --- INICIANDO ENSAMBLAJE (Movis Engine) ---")
        sprite_controller.reset_controller() 
        prof = load_profile(profile_name)
        is_full_screen = str(layout_mode).lower() == "full_screen"
        
        with wave.open(audio_path, 'rb') as f:
            duration = float(f.getnframes() / f.getframerate())
        
        print(f"⏳ Duración: {duration:.2f}s | Perfil: {profile_name}")
        
        comp = mv.layer.Composition(size=self.canvas_size, duration=duration)
        scale_ratio = 1.0 

        # --- 1. CAPA FONDO ---
        print(f"🖼️ Configurando capa de fondo...")
        if is_full_screen:
            bg_video_path = prof.get("background", {}).get("path")
            if bg_video_path and os.path.exists(bg_video_path):
                # Cargamos el video base una sola vez
                v_base = mv.layer.Video(bg_video_path)
                
                # Añadimos la capa ajustada a la duración total de la composición
                l_bg = comp.add_layer(v_base, offset=0, end_time=duration)
                
                # Aplicamos escala para cubrir el canvas y el desenfoque
                scale_factor = max(self.canvas_size[0] / v_base.size[0], self.canvas_size[1] / v_base.size[1])
                l_bg.scale.set(scale_factor)
                l_bg.add_effect(mv.effect.GaussianBlur(radius=10))
                
                print(f" ↳ Fondo aplicado con desenfoque.")
        else:
            # Lógica para cuando no es full_screen (mantiene el blur)
            for i, path in enumerate(clip_paths):
                if i >= len(segments) or not os.path.exists(path): continue
                s_t = float(segments[i]["start"])
                e_t = float(segments[i+1]["start"] if i < len(segments)-1 else duration)
                v_layer = mv.layer.Video(path)
                l_bg = comp.add_layer(v_layer, offset=s_t, end_time=e_t)
                l_bg.position.set((self.canvas_size[0]/2, self.canvas_size[1]/2))
                l_bg.scale.set(max(self.canvas_size[0]/v_layer.size[0], self.canvas_size[1]/v_layer.size[1]))
                l_bg.add_effect(mv.effect.GaussianBlur(radius=10))

        # --- 2. CAPA CLIPS DE STOCK ---
        if is_full_screen:
            print(f"🎞️ Superponiendo clips de stock...")
            side = int(600 * scale_ratio) 
            center_y_stock = self.canvas_size[1] * 0.30 
            for i, path in enumerate(clip_paths):
                if i >= len(segments) or not os.path.exists(path): continue
                s_t = float(segments[i]["start"])
                e_t = float(segments[i+1]["start"] if i < len(segments)-1 else duration)
                v_src = mv.layer.Video(path)
                l_st = comp.add_layer(v_src, offset=s_t, end_time=e_t)
                l_st.position.set((self.canvas_size[0]/2, center_y_stock))
                s_factor = max(side / v_src.size[0], side / v_src.size[1])
                l_st.scale.set(s_factor)
                l_st.opacity.enable_motion()
                l_st.opacity.motion.extend(keyframes=[0.0, 0.3], values=[0.0, 1.0])

        # --- 3. CAPA PERSONAJE (OPTIMIZADA CON CACHE) ---
        char_cfg = prof.get("character", {})
        if char_cfg.get("enabled", False):
            print(f"👤 Procesando personaje...")
            char_pos = char_cfg.get("position", {"x": 540, "y": 1500})
            base_pos = (float(char_pos["x"]), float(char_pos["y"]))
            base_scale = float(char_cfg.get("scale", 1.0))
            sprite_pack = char_cfg.get("sprite_pack", "")
            fade_dur = 0.12  
            
            for i, seg in enumerate(segments):
                s_start = float(seg["start"])
                s_next = float(segments[i+1]["start"]) if i < len(segments)-1 else duration
                s_end = min(s_next + fade_dur, duration)

                img_path = sprite_controller.pick_sprite(seg["phrase"], sprite_pack)
                if os.path.exists(img_path):
                    # Cache de imagen para evitar I/O redundante
                    if img_path not in self._sprite_cache:
                        self._sprite_cache[img_path] = mv.layer.Image(img_path)
                    
                    img_layer = self._sprite_cache[img_path]
                    l_char = comp.add_layer(img_layer, offset=s_start, end_time=s_end)
                    l_char.position.set(base_pos)
                    l_char.scale.set(base_scale)
                    
                    actual_fade = min(fade_dur, (s_end - s_start) / 2.1)
                    l_char.opacity.enable_motion()
                    l_char.opacity.motion.extend(
                        keyframes=[0.0, actual_fade, (s_end - s_start) - actual_fade, (s_end - s_start)],
                        values=[0.0, 1.0, 1.0, 0.0]
                    )
            print(f"✅ Personaje configurado.")

        # --- 4. RENDER VISUAL ---
        temp_video = os.path.join(job_path, "visual_raw.mp4")
        print(f"⚙️ Iniciando renderizado Raw a 24 FPS...")
        comp.write_video(temp_video, fps=24, audio=False) 

        # --- 5. SUBTÍTULOS Y FFmpeg ---
        final_margin = 0 if is_full_screen else 200 
        ass_path = self._generate_ass(segments, prof, preset_from_front, final_margin)

        final_path = self._run_final_ffmpeg(temp_video, audio_path, ass_path)

        # --- LIMPIEZA DE MEMORIA ---
        self._sprite_cache.clear()
        gc.collect()

        return final_path

    def _run_final_ffmpeg(self, video_in, audio_in, ass_path):
        print(f"🚀 Render final con FFmpeg (NVENC)...")
        ass_p = os.path.abspath(ass_path).replace("\\", "/").replace(":", "\\:")
        
        cmd = [
            "ffmpeg", "-y",
            "-hwaccel", "cuda",             # Aceleración de decodificación
            "-i", video_in,
            "-i", audio_in,
            "-vf", f"ass='{ass_p}'",
            "-c:v", "h264_nvenc",
            "-preset", "p1",                # p4 ofrece mejor balance que p2
            "-tune", "hq",
            "-rc", "vbr",                   # Bitrate variable (más eficiente)
            "-cq", "24",                    # Calidad constante
            "-maxrate", "12M",              # Techo de bitrate
            "-bufsize", "24M",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest",
            self.output_path
        ]
        
        try:
            subprocess.run(cmd, check=True)
            print(f"🏁 PROCESO COMPLETADO: {self.output_path}")
        except subprocess.CalledProcessError as e:
            print(f"❌ Error FFmpeg: {e}")
            raise e
            
        return self.output_path