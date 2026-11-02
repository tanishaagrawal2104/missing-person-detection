import sys
import unittest
import json
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

from app.api import valid_references
from app.models import ReferenceImage
from app.schemas import CandidateResponse, SearchJobResponse
from app.services.ai import (
    cosine_distance,
    generate_reference_embedding,
    represent,
    validate_embedding,
)


class EmbeddingValidationTests(unittest.TestCase):
    def test_cosine_distance_for_valid_embeddings(self):
        self.assertAlmostEqual(cosine_distance([1, 0], [1, 0]), 0.0)

    def test_invalid_embeddings_are_not_compared(self):
        for invalid in (None, [], [None], ["not-a-number"]):
            self.assertIsNone(cosine_distance([1, 0], invalid))
            self.assertIsNone(cosine_distance(invalid, [1, 0]))

    def test_zero_vectors_and_mismatched_dimensions_are_not_compared(self):
        self.assertIsNone(cosine_distance([0, 0], [1, 0]))
        self.assertIsNone(cosine_distance([1, 0], [1, 0, 0]))

    def test_validate_embedding_rejects_non_finite_values(self):
        with self.assertRaises(ValueError):
            validate_embedding([float("nan")])
        with self.assertRaises(ValueError):
            validate_embedding([float("inf")])

    def test_represent_rejects_missing_deepface_embedding(self):
        fake_deepface = SimpleNamespace(
            DeepFace=SimpleNamespace(
                represent=lambda *args, **kwargs: [{"embedding": None}]
            )
        )
        with patch.dict(sys.modules, {"deepface": fake_deepface}):
            with self.assertRaisesRegex(ValueError, "invalid representation"):
                represent(Image.new("RGB", (2, 2)))

    def test_search_reference_filter_skips_invalid_candidates(self):
        valid = SimpleNamespace(id="valid", representation=[1, 0])
        invalid = SimpleNamespace(id="invalid", representation=[None, 0])
        self.assertEqual(valid_references([invalid, valid]), [valid])

    def test_search_response_models_accept_orm_objects(self):
        from datetime import datetime, timezone
        from uuid import uuid4

        candidate = SimpleNamespace(
            id=uuid4(), case_id=uuid4(), reference_image_id=uuid4(),
            status="unreviewed", distance=0.1,
            frame_timestamp_seconds=None, source_storage_key=None,
            created_at=datetime.now(timezone.utc),
        )
        job = SimpleNamespace(
            id=uuid4(), case_id=uuid4(), case_name="Example Person",
            job_type="image", status="queued",
            progress=0, error_message=None, created_at=datetime.now(timezone.utc),
            candidates=[candidate],
        )
        self.assertEqual(len(SearchJobResponse.model_validate(job).candidates), 1)
        self.assertEqual(CandidateResponse.model_validate(candidate).status, "unreviewed")

    def test_embedding_storage_round_trip_is_a_json_number_array(self):
        stored = json.loads(json.dumps([1.0, -2.5, 3.25]))
        self.assertEqual(validate_embedding(stored), [1.0, -2.5, 3.25])
        self.assertTrue(ReferenceImage.__table__.c.representation.type.none_as_null)

    def test_reference_regeneration_uses_first_detected_face(self):
        expected = [0.1, 0.2]
        with patch("app.services.ai.decode_image", return_value=Image.new("RGB", (2, 2))), patch(
            "app.services.ai.detect_faces", return_value=[
            SimpleNamespace(image=Image.new("RGB", (2, 2)), index=0)
        ]), patch("app.services.ai.represent", return_value=expected) as represent_mock:
            result = generate_reference_embedding(b"image bytes")
        self.assertEqual(result, expected)
        represent_mock.assert_called_once()

    def test_reference_regeneration_rejects_images_without_faces(self):
        with patch("app.services.ai.decode_image", return_value=Image.new("RGB", (2, 2))), patch(
            "app.services.ai.detect_faces", return_value=[]
        ):
            with self.assertRaisesRegex(ValueError, "No face detected"):
                generate_reference_embedding(b"image bytes")


if __name__ == "__main__":
    unittest.main()
