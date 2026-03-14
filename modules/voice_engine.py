import os, json, re, time, unicodedata, torch, subprocess, shutil, requests, warnings
from pydub import AudioSegment
from functools import lru_cache
from faster_whisper import WhisperModel
from elevenlabs.client import ElevenLabs
import config  # Importación del archivo central de configuración

os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
warnings.filterwarnings("ignore", category=UserWarning)

# --- CONFIGURACIÓN ELEVENLABS (Mismo sistema que AssetManager) ---
ELEVEN_API_KEY = getattr(config, "ELEVENLABS_API_KEY", None)

if not ELEVEN_API_KEY or ELEVEN_API_KEY.strip() in ("", "###"):
    print("⚠️ ELEVENLABS_API_KEY no configurada en config.py. Se usará Piper por defecto.")
    client = None
else:
    client = ElevenLabs(api_key=ELEVEN_API_KEY)

# --- OPTIMIZACIÓN DE CARGA (Whisper) ---
_model = None
_ZERO_WIDTH = dict.fromkeys([0x200B, 0x200C, 0x200D, 0xFEFF, 0x2060, 0x00AD], None)

def get_whisper_model():
    global _model
    if _model is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"
        _model = WhisperModel(
            "medium", 
            device=device, 
            compute_type="float16" if device == "cuda" else "int8"
        )
    return _model

# --- LIMPIEZA Y PROSODIA ---
def sanitize_for_piper(text: str) -> str:
    s = unicodedata.normalize("NFC", text).translate(_ZERO_WIDTH)
    s = re.sub(r"[^0-9A-Za-zñÑÁÉÍÓÚÜáéíóúü\s\.\,\!\?\;\:\(\)\-\"']", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s if s.endswith((".", "!", "?")) else s + "."

@lru_cache(maxsize=32)
def humanize_text(s: str) -> str:
    s = re.sub(r"\s+(pero|porque|entonces|además|aunque|sin embargo)\s+", r", \1 ", s, flags=re.IGNORECASE)
    words = s.split()
    if len(words) > 22:
        for i in range(20, len(words), 20):
            if i < len(words) and not words[i].endswith((",", ".", "!", "?")):
                words[i] += ","
        s = " ".join(words)
    return s

# --- GENERADOR DE AUDIO (ELEVENLABS SDK V1 + PIPER FALLBACK) ---
async def generate_audio(texto, voice="FN2V6hDljTL9BYyYuy7p", save_path=None, **kwargs):
    """
    Genera audio usando ElevenLabs (SDK v1) si hay API Key y el ID es reconocido, 
    de lo contrario usa Piper localmente.
    """
    if not save_path:
        save_path = f"assets/audio/voice_{int(time.time())}.wav"
    
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    texto_ready = humanize_text(sanitize_for_piper(texto))

    # 1. ¿Es ElevenLabs o Piper?
    # Usamos ElevenLabs solo si el cliente existe y la voz no es un modelo local es_ES
    is_elevenlabs = client is not None and "es_ES" not in voice

    if is_elevenlabs:
        try:
            print(f"🎙️ Generando con ElevenLabs API (Voice: {voice})...")
            style_cfg = kwargs.get("elevenlabs_style", {})
            
            # Llamada oficial SDK v1
            audio_iterator = client.text_to_speech.convert(
                text=texto_ready,
                voice_id=voice,
                model_id="eleven_flash_v2_5",
                output_format="mp3_44100_128",
                voice_settings={
                    "stability": style_cfg.get("stability", 0.65),
                    "similarity_boost": style_cfg.get("similarity_boost", 0.85),
                    "style": style_cfg.get("style", 0.10),
                    "use_speaker_boost": True
                }
            )

            # Guardar MP3 temporal
            temp_mp3 = save_path.replace(".wav", ".mp3")
            with open(temp_mp3, "wb") as f:
                for chunk in audio_iterator:
                    if chunk:
                        f.write(chunk)

            # Convertir a WAV 48kHz para consistencia en el motor de video
            audio = AudioSegment.from_file(temp_mp3)
            if kwargs.get("postprocess_mode") == "radio":
                audio = audio.normalize(headroom=0.1) + 3
            
            audio.set_frame_rate(48000).set_channels(1).export(save_path, format="wav", codec="pcm_s16le")
            
            if os.path.exists(temp_mp3): os.remove(temp_mp3)
            return save_path

        except Exception as e:
            print(f"⚠️ Error ElevenLabs: {e}. Reintentando con Piper...")
            voice = "es_ES-sharvard-medium" 

    # 2. Lógica de Piper (Fallback)
    base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    model_path = os.path.join(base_path, "assets", "models", f"{voice}.onnx")
    
    if not os.path.exists(model_path):
        voice = "es_ES-sharvard-medium"
        model_path = os.path.join(base_path, "assets", "models", f"{voice}.onnx")

    command = [
        "piper", "--model", model_path, "--output_file", save_path,
        "--length_scale", "1.0", "--sentence_silence", "0.4"
    ]
    
    try:
        proc = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        proc.communicate(input=texto_ready.encode("utf-8"), timeout=60)
        
        # Normalizar siempre a 48kHz para evitar errores de renderizado
        audio = AudioSegment.from_wav(save_path).set_frame_rate(48000).set_channels(1)
        audio.export(save_path, format="wav", codec="pcm_s16le")
        return save_path
    except Exception as e:
        print(f"❌ Error crítico de Voz: {e}")
        return None

# --- WHISPER Y TIMESTAMPS ---
def get_word_timestamps(audio_path, job_path=None, original_text=""):
    model = get_whisper_model()
    segments, info = model.transcribe(
        audio_path, 
        language="es",
        word_timestamps=True,
        initial_prompt=original_text[:1000]
    )

    words_data = []
    for segment in segments:
        if segment.words:
            for w in segment.words:
                raw = w.word.strip()
                clean = re.sub(r"\W+", "", raw).upper()
                if clean:
                    words_data.append({
                        "word": clean,
                        "raw_word": raw,
                        "start": round(w.start, 3),
                        "end": round(w.end, 3)
                    })
    
    if job_path:
        os.makedirs(job_path, exist_ok=True)
        with open(os.path.join(job_path, "timestamps.json"), "w", encoding="utf-8") as f:
            json.dump(words_data, f, indent=4, ensure_ascii=False)

    return words_data