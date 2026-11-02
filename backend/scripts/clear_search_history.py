"""Clear all search jobs and their cascaded candidate matches.

Run from the backend directory:

    python scripts/clear_search_history.py
    python scripts/clear_search_history.py --confirm

The default invocation is a dry run. This script never deletes users, cases,
reference images, sightings, or audit records.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.db.session import SessionLocal
from app.models import SearchJob


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Clear all search history and associated candidate matches."
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Delete the selected search jobs and their exact query media files.",
    )
    return parser.parse_args()


def resolve_query_file(
    upload_directory: Path, query_storage_key: str
) -> Path:
    upload_root = upload_directory.resolve()
    query_path = (upload_root / query_storage_key).resolve()
    try:
        query_path.relative_to(upload_root)
    except ValueError as exc:
        raise ValueError(
            f"Query media path escapes upload directory: {query_storage_key!r}"
        ) from exc
    return query_path


def main() -> None:
    args = parse_args()
    upload_directory = Path(settings.upload_directory)

    with SessionLocal() as db:
        jobs = db.scalars(
            select(SearchJob)
            .options(selectinload(SearchJob.candidate_matches))
            .order_by(SearchJob.created_at)
        ).all()

        query_files: set[Path] = set()
        for job in jobs:
            if job.query_storage_key:
                query_files.add(
                    resolve_query_file(upload_directory, job.query_storage_key)
                )

        candidate_count = sum(len(job.candidate_matches) for job in jobs)
        existing_query_files = {path for path in query_files if path.is_file()}

        print(f"Search jobs: {len(jobs)}")
        print(f"Candidate matches: {candidate_count}")
        print(f"Referenced query media files: {len(query_files)}")
        print(f"Existing query media files: {len(existing_query_files)}")

        if not args.confirm:
            print("Dry run only. Nothing was deleted. Re-run with --confirm to apply.")
            return

        for job in jobs:
            db.delete(job)
        db.commit()

    deleted_files = 0
    failed_files: list[str] = []
    for query_file in existing_query_files:
        try:
            query_file.unlink()
            deleted_files += 1
        except OSError as exc:
            failed_files.append(f"{query_file}: {exc}")

    print(f"Deleted search jobs: {len(jobs)}")
    print(f"Deleted candidate matches through ORM cascade: {candidate_count}")
    print(f"Deleted query media files: {deleted_files}")
    if failed_files:
        print("Query media files not deleted:")
        for failure in failed_files:
            print(f"  {failure}")


if __name__ == "__main__":
    main()
