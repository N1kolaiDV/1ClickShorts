import spacy
from functools import lru_cache

# --- CARGA OPTIMIZADA DEL MODELO ---
def load_nlp():
    try:
        return spacy.load("es_core_news_sm")
    except OSError:
        import os
        print("Descargando modelo de spaCy...")
        os.system("python -m spacy download es_core_news_sm")
        return spacy.load("es_core_news_sm")

# Cargamos el modelo una sola vez al importar el módulo
nlp = load_nlp()

# CONCEPTOS CLAVE: Usamos lemas (raíces) para máxima coincidencia
# Ejemplo: "disciplinado", "disciplinas" -> "disciplina"
CONCEPT_MAP = {
    "disciplina": "workout gym motivation athlete",
    "atencion": "focused person eyes deep work",
    "dopamina": "phone addiction scrolling digital",
    "amor": "self care peaceful nature",
    "acero": "molten metal fire sparks",
    "forja": "blacksmith hammer hitting anvil",
    "mundo": "earth city lights night",
    "ganador": "successful man suit luxury",
    "suerte": "dice casino gambling clover",
    "tiempo": "sand clock hourglass timelapse",
    "mente": "meditation focus zen",
    "dinero": "dollars falling cash luxury",
    "madrugada": "sunrise fog morning window",
}

@lru_cache(maxsize=128)
def extract_keywords(text: str):
    """
    Extrae palabras clave optimizadas. 
    Usa lru_cache para no procesar la misma frase varias veces.
    """
    if not text or len(text.strip()) < 3:
        return "cinematic lifestyle"

    doc = nlp(text.lower())
    
    # 1. Intentar detectar conceptos abstractos del diccionario (por lema)
    for token in doc:
        if token.lemma_ in CONCEPT_MAP:
            return CONCEPT_MAP[token.lemma_]

    # 2. Si no hay concepto directo, extraer Sustantivos y Adjetivos
    # Priorizamos sustantivos sobre adjetivos para la búsqueda visual
    keywords = [token.text for token in doc 
                if token.pos_ in ["NOUN", "PROPN"] and not token.is_stop]
    
    # Si no hay sustantivos, añadimos adjetivos o verbos
    if len(keywords) < 2:
        extra = [token.text for token in doc 
                 if token.pos_ in ["ADJ", "VERB"] and not token.is_stop]
        keywords.extend(extra)

    # Limpiamos y limitamos a 3 términos para no confundir a la API de Pexels
    result = " ".join(dict.fromkeys(keywords[:3])) # dict.fromkeys elimina duplicados preservando orden
    
    return result if result else "cinematic lifestyle"