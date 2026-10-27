import hashlib
from dataclasses import dataclass
from functools import lru_cache
from io import BytesIO
from pathlib import Path

import numpy as np
from PIL import Image

from app.core.config import settings


@dataclass
class DetectedFace:
    image: Image.Image
    index: int


def processing_signature() -> str:
    value = "|".join(
        (settings.face_detector_weights, settings.deepface_model_name,
         settings.deepface_detector_backend, str(settings.ai_image_size))
    )
    return hashlib.sha256(value.encode()).hexdigest()


def decode_image(content: bytes) -> Image.Image:
    try:
        image = Image.open(BytesIO(content)).convert("RGB")
        image.load()
        return image
    except Exception as exc:
        raise ValueError("Unreadable image") from exc


@lru_cache(maxsize=1)
def _detector():
    weights = Path(settings.face_detector_weights)
    if not weights.is_file():
        raise RuntimeError(
            f"Face detector weights not found: {weights}. "
            "Configure FACE_DETECTOR_WEIGHTS with a YOLOv8 face model."
        )
    from ultralytics import YOLO

    return YOLO(str(weights))


def detect_faces(image: Image.Image) -> list[DetectedFace]:
    detector = _detector()
    result = detector.predict(
        source=np.asarray(image), imgsz=settings.ai_image_size, verbose=False
    )[0]
    faces: list[DetectedFace] = []
    for index, box in enumerate(result.boxes.xyxy.cpu().numpy().astype(int)):
        left, top, right, bottom = box.tolist()
        crop = image.crop((max(0, left), max(0, top), right, bottom))
        if crop.width and crop.height:
            faces.append(DetectedFace(crop, index))
    return faces


def represent(face: Image.Image) -> list[float]:
    from deepface import DeepFace

    result = DeepFace.represent(
        np.asarray(face),
        model_name=settings.deepface_model_name,
        detector_backend=settings.deepface_detector_backend,
        enforce_detection=False,
    )
    if not result or "embedding" not in result[0]:
        raise ValueError("DeepFace did not produce a representation")
    return [float(value) for value in result[0]["embedding"]]


def cosine_distance(left: list[float], right: list[float]) -> float:
    left_array, right_array = np.asarray(left), np.asarray(right)
    denominator = np.linalg.norm(left_array) * np.linalg.norm(right_array)
    if not denominator:
        return 1.0
    return float(1 - np.dot(left_array, right_array) / denominator)
