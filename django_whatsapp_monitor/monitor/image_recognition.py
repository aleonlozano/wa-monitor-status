"""Módulo de reconocimiento de imágenes basado en features (ORB).

En vez de comparar solo histogramas, usamos ORB para detectar puntos clave
y comparar la estructura de la imagen. Esto es más robusto frente a:
- Texto añadido.
- Pequeñas variaciones de color.
- Reencuadres leves.

Se considera match cuando el ratio de "buenos" emparejamientos supera un umbral.
"""

import cv2
import os

def _orb_compare_mats(img_a, img_b, min_matches=10, good_match_ratio=0.15):
    """
    Compara dos imágenes (matrices OpenCV) usando ORB + BFMatcher.
    Devuelve (match_bool, score) donde score es la proporción de 'good matches'.
    """
    if img_a is None or img_b is None:
        return False, 0.0

    # Convertir a escala de grises si vienen en color
    if len(img_a.shape) == 3:
        img_a = cv2.cvtColor(img_a, cv2.COLOR_BGR2GRAY)
    if len(img_b.shape) == 3:
        img_b = cv2.cvtColor(img_b, cv2.COLOR_BGR2GRAY)

    # Redimensionar a un tamaño estándar para hacer la comparación más robusta
    size = (400, 400)
    img_a = cv2.resize(img_a, size)
    img_b = cv2.resize(img_b, size)

    orb = cv2.ORB_create(500)
    kp1, des1 = orb.detectAndCompute(img_a, None)
    kp2, des2 = orb.detectAndCompute(img_b, None)

    if des1 is None or des2 is None or len(kp1) == 0 or len(kp2) == 0:
        return False, 0.0

    bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
    matches = bf.knnMatch(des1, des2, k=2)

    if not matches:
        return False, 0.0

    good_matches = []
    for m, n in matches:
        if m.distance < 0.75 * n.distance:
            good_matches.append(m)

    total_matches = len(matches)
    good = len(good_matches)

    if total_matches == 0:
        return False, 0.0

    score = good / float(total_matches)

    # Condición de match: suficiente cantidad absoluta y buena proporción
    is_match = (good >= min_matches) and (score >= good_match_ratio)

    # Debug opcional:
    # print(f"[ORB] total={total_matches}, good={good}, score={score:.3f}, match={is_match}")

    return is_match, score

def compare_images(story_path: str, frame_path: str,
                   max_video_frames: int = 10,
                   min_matches: int = 10,
                   good_match_ratio: float = 0.15) -> bool:
    """
    Compara la media descargada de la historia (story_path) con el fotograma de referencia (frame_path).

    - story_path: ruta de la historia descargada (puede ser imagen o video).
    - frame_path: ruta del fotograma de referencia (imagen subida en la campaña).
    - max_video_frames: número máximo de frames a muestrear en caso de video.
    - min_matches: número mínimo de 'good matches' para considerar un match.
    - good_match_ratio: ratio mínimo de buenos matches respecto al número total de matches.

    Devuelve True si alguna imagen (la propia o algún frame del video) coincide con el fotograma de referencia.
    """
    if not story_path or not frame_path:
        return False

    if not os.path.exists(story_path) or not os.path.exists(frame_path):
        return False

    # Cargar imagen de referencia (fotograma objetivo)
    ref_img = cv2.imread(frame_path)
    if ref_img is None:
        # print(f"[compare_images] No se pudo leer la imagen de referencia: {frame_path}")
        return False

    ext = os.path.splitext(story_path)[1].lower()

    # Caso 1: la historia es una imagen
    if ext in ['.jpg', '.jpeg', '.png', '.bmp', '.webp']:
        cand_img = cv2.imread(story_path)
        if cand_img is None:
            # print(f"[compare_images] No se pudo leer la imagen candidata: {story_path}")
            return False

        match, score = _orb_compare_mats(cand_img, ref_img,
                                         min_matches=min_matches,
                                         good_match_ratio=good_match_ratio)
        # print(f"[compare_images] Imagen vs imagen → match={match}, score={score:.3f}")
        return match

    # Caso 2: la historia es un video → muestrear varios frames
    if ext in ['.mp4', '.mov', '.m4v', '.avi', '.mkv']:
        cap = cv2.VideoCapture(story_path)
        if not cap.isOpened():
            # print(f"[compare_images] No se pudo abrir el video: {story_path}")
            return False

        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
        if frame_count <= 0:
            frame_indices = list(range(max_video_frames))
        else:
            step = max(1, frame_count // max_video_frames)
            frame_indices = list(range(0, frame_count, step))[:max_video_frames]

        # print(f"[compare_images] Video detectado. frame_count={frame_count}, muestreando frames={frame_indices}")

        idx = 0
        best_score = 0.0
        found_match = False

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            if idx in frame_indices:
                match, score = _orb_compare_mats(frame, ref_img,
                                                 min_matches=min_matches,
                                                 good_match_ratio=good_match_ratio)
                # print(f"[compare_images] Frame idx={idx} → match={match}, score={score:.3f}")
                if score > best_score:
                    best_score = score
                if match:
                    found_match = True
                    break

            idx += 1

        cap.release()
        # print(f"[compare_images] Resultado final video vs imagen → found_match={found_match}, best_score={best_score:.3f}")
        return found_match

    # Otros tipos de archivo: por ahora no se comparan
    # print(f"[compare_images] Extensión no soportada para story_path: {story_path}")
    return False
