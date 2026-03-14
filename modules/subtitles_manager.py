import pysubs2
import os

# --- CONFIGURACIÓN ---
DEFAULT_PRESET_DIR = "assets/subtitles/presets"
OUTPUT_DIR = "assets/subtitles"

def generate_styled_subs(words_data, preset_name="mrbeast.ass"):
    """
    Genera subtítulos estilizados con soporte para resaltado dinámico.
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    preset_path = os.path.join(DEFAULT_PRESET_DIR, preset_name)
    
    subs = pysubs2.SSAFile()
    
    # 1. Gestión Inteligente de Estilos
    if os.path.exists(preset_path):
        try:
            template = pysubs2.load(preset_path)
            subs.styles = template.styles
            subs.info.update(template.info) # Mantiene resolución y metadatos
        except Exception as e:
            print(f"Error cargando preset: {e}")
    
    # Aseguramos que exista un estilo 'Default' si el preset falla
    if "Default" not in subs.styles:
        subs.styles["Default"] = pysubs2.SSAStyle(
            fontname="Arial Black", fontsize=70, 
            primarycolor=pysubs2.Color(255, 255, 255),
            outline=3, alignment=2 # Centrado abajo
        )

    # 2. Generación de Eventos
    # Optimizamos el loop para transformar las palabras a mayúsculas (estética viral)
    for w in words_data:
        start_ms = int(w['start'] * 1000)
        end_ms = int(w['end'] * 1000)
        
        # Opcional: Podrías añadir etiquetas de animación aquí (ej: {\fscx110\fscy110})
        text = w['word'].upper().strip()
        
        line = pysubs2.SSAEvent(start=start_ms, end=end_ms, text=text)
        line.style = "Default"
        subs.append(line)
    
    # 3. Guardado Limpio
    output_path = os.path.join(OUTPUT_DIR, "final_subs.ass")
    subs.save(output_path)
    
    return output_path