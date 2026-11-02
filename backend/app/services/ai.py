import hashlib
import math
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


def validate_embedding(value: object) -> list[float]:
    if value is None or isinstance(value, (str, bytes)):
        raise ValueError("Embedding is missing or not a sequence")
    try:
        values = list(value)  # type: ignore[arg-type]
    except TypeError as exc:
        raise ValueError("Embedding is not a sequence") from exc
    if not values:
        raise ValueError("Embedding is empty")
    try:
        embedding = [float(item) for item in values]
    except (TypeError, ValueError) as exc:
        raise ValueError("Embedding contains non-numeric values") from exc
    if not all(math.isfinite(item) for item in embedding):
        raise ValueError("Embedding contains non-finite values")
    return embedding


def represent(face: Image.Image) -> list[float]:
    from deepface import DeepFace

    result = DeepFace.represent(
        np.asarray(face),
        model_name=settings.deepface_model_name,
        detector_backend=settings.deepface_detector_backend,
        enforce_detection=False,
    )
    if not isinstance(result, list) or not result or not isinstance(result[0], dict):
        raise ValueError("DeepFace did not produce a representation")
    try:
        return validate_embedding(result[0].get("embedding"))
    except ValueError as exc:
        raise ValueError("DeepFace returned an invalid representation") from exc


def generate_reference_embedding(content: bytes) -> list[float]:
    faces = detect_faces(decode_image(content))
    if not faces:
        raise ValueError("No face detected in reference image")
    return represent(faces[0].image)


def cosine_distance(left: object, right: object) -> float | None:
    try:
        left_values = validate_embedding(left)
        right_values = validate_embedding(right)
    except ValueError:
        return None
    if len(left_values) != len(right_values):
        return None
    left_array = np.asarray(left_values, dtype=float)
    right_array = np.asarray(right_values, dtype=float)
    left_norm = np.linalg.norm(left_array)
    right_norm = np.linalg.norm(right_array)
    denominator = left_norm * right_norm
    if not math.isfinite(left_norm) or not math.isfinite(right_norm) or not denominator:
        return None
    distance = 1 - np.dot(left_array, right_array) / denominator
    return float(distance) if math.isfinite(distance) else None
