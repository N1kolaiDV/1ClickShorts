import os
import random

_last_pose = None

def reset_controller():
    global _last_pose
    _last_pose = None

def pick_sprite(segment_phrase: str, sprite_pack: str) -> str:
    global _last_pose
    t = segment_phrase.lower() if segment_phrase else ""
    sprite_pack = os.path.abspath(sprite_pack)
    
    poses = {
        "base": os.path.join(sprite_pack, "base.png"),
        "pose_1": os.path.join(sprite_pack, "pose_1.png"),
        "pose_2": os.path.join(sprite_pack, "pose_2.png"),
        "pose_3": os.path.join(sprite_pack, "pose_3.png"),
    }

    selected = None
    
    # 1. Detección por palabras clave
    if any(w in t for w in ["error", "cuidado", "ojo", "pero", "peligro", "mal"]):
        selected = poses["pose_3"]
    elif any(w in t for w in ["mira", "fíjate", "observa", "dato", "clave", "dinero", "cien", "ocho"]):
        selected = poses["pose_2"]
    elif any(w in t for w in ["recuerda", "resumen", "finalmente", "éxito", "aprende", "secreto"]):
        selected = poses["pose_1"]

    # 2. LÓGICA ANTIFREEZE: Si la palabra clave nos da la MISMA que la anterior, 
    # forzamos un cambio aleatorio para que el video tenga vida.
    if selected == _last_pose or not selected:
        opciones = [poses["base"], poses["pose_1"], poses["pose_2"], poses["pose_3"]]
        # Eliminamos la última para obligar a un cambio visual
        if _last_pose in opciones:
            opciones.remove(_last_pose)
        selected = random.choice(opciones)

    _last_pose = selected
    
    # TRUCO FINAL: Devolvemos la ruta absoluta pero nos aseguramos de que
    # Python no esté pasando una referencia a un objeto string viejo.
    return str(os.path.abspath(selected))