"""Clear reference images while preserving cases and users.

Run from the backend directory:

    python scripts/clear_reference_images.py
    python scripts/clear_reference_images.py --confirm

The default invocation is a dry run. This script preserves users, cases,
sightings, audit records, and search jobs.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from sqlalchemy import select

from app.core.config import settings
from app.db.session import SessionLocal
from app.models import CandidateMatch, ReferenceImage


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Clear all reference images and their dependent candidates."
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Delete reference images, dependent candidates, and exact image files.",
    )
    return parser.parse_args()


def resolve_reference_file(
    upload_directory: Path, storage_key: str
) -> Path:
    upload_root = upload_directory.resolve()
    image_path = (upload_root / storage_key).resolve()
    try:
        image_path.relative_to(upload_root)
    except ValueError as exc:
        raise ValueError(
            f"Reference image path escapes upload directory: {storage_key!r}"
        ) from exc
    return image_path


def main() -> None:
    args = parse_args()
    upload_directory = Path(settings.upload_directory)

    with SessionLocal() as db:
        references = db.scalars(
            select(ReferenceImage).order_by(ReferenceImage.created_at)
        ).all()
        reference_ids = [reference.id for reference in references]
        candidates = (
            db.scalars(
                select(CandidateMatch).where(
                    CandidateMatch.reference_image_id.in_(reference_ids)
                )
            ).all()
            if reference_ids
            else []
        )
        affected_job_ids = {candidate.search_job_id for candidate in candidates}

        image_files = {
            resolve_reference_file(upload_directory, reference.storage_key)
            for reference in references
        }
        existing_files = {path for path in image_files if path.is_file()}
        missing_files = image_files - existing_files

        print(f"ReferenceImage rows: {len(references)}")
        print(f"Dependent CandidateMatch rows: {len(candidates)}")
        print(f"Affected SearchJob rows: {len(affected_job_ids)}")
        print(f"Exact image files referenced: {len(image_files)}")
        print(f"Existing image files: {len(existing_files)}")
        print(f"Missing image files: {len(missing_files)}")

        if not args.confirm:
            print("Dry run only. Nothing was deleted. Re-run with --confirm to apply.")
            return

        for candidate in candidates:
            db.delete(candidate)
        for reference in references:
            db.delete(reference)
        db.commit()

    deleted_files = 0
    failed_files: list[str] = []
    for image_file in existing_files:
        try:
            image_file.unlink()
            deleted_files += 1
        except OSError as exc:
            failed_files.append(f"{image_file}: {exc}")

    print(f"Deleted ReferenceImage rows: {len(references)}")
    print(f"Deleted dependent CandidateMatch rows: {len(candidates)}")
    print("Deleted SearchJob rows: 0 (search jobs are preserved)")
    print(f"Deleted exact image files: {deleted_files}")
    print(f"Image files already missing: {len(missing_files)}")
    if failed_files:
        print("Image files not deleted:")
        for failure in failed_files:
            print(f"  {failure}")


if __name__ == "__main__":
    main()
