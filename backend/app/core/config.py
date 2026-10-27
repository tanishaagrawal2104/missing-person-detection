from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Missing Person Detection API"
    environment: str = "development"
    database_url: str
    secret_key: str
    access_token_expire_minutes: int = 30
    frontend_origin: str = "http://localhost:5173"
    max_upload_size_bytes: int = 5 * 1024 * 1024
    upload_directory: str = "uploads"
    rate_limit_per_minute: int = 10
    face_detector_weights: str = "weights/yolov8n-face.pt"
    deepface_model_name: str = "Facenet512"
    deepface_detector_backend: str = "skip"
    face_match_distance_threshold: float = 0.30
    video_frame_interval_seconds: float = 1.0
    max_video_size_bytes: int = 50 * 1024 * 1024
    max_video_duration_seconds: int = 300
    ai_image_size: int = 640

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
