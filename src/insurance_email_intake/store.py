import re
from pathlib import Path

from insurance_email_intake.models import IntakeRecord

SOURCE_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


class RecordStore:
    """One JSON file per processed email; the source of idempotency."""

    def __init__(self, state_dir: Path) -> None:
        self.state_dir = state_dir
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, source_id: str) -> Path:
        if not SOURCE_ID_PATTERN.fullmatch(source_id):
            raise ValueError("Invalid source_id.")
        return self.state_dir / f"{source_id}.json"

    def get(self, source_id: str) -> IntakeRecord | None:
        path = self._path(source_id)
        if not path.exists():
            return None
        return IntakeRecord.model_validate_json(path.read_text(encoding="utf-8"))

    def save(self, record: IntakeRecord) -> None:
        path = self._path(record.email.source_id)
        temporary = path.with_name(f"{path.name}.tmp")
        temporary.write_text(record.model_dump_json(indent=2), encoding="utf-8")
        temporary.replace(path)

    def list_records(self) -> list[IntakeRecord]:
        records = [
            IntakeRecord.model_validate_json(path.read_text(encoding="utf-8"))
            for path in self.state_dir.glob("*.json")
        ]
        return sorted(records, key=lambda record: record.processed_at, reverse=True)
