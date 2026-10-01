"""Serializable provenance records without persistence or database side effects."""
from dataclasses import asdict, dataclass
from datetime import datetime
import json
import re


@dataclass(frozen=True)
class ArtifactProvenance:
    source_url: str
    download_timestamp: datetime
    sha256: str
    file_size: int
    row_count: int | None = None
    schema_digest: str | None = None
    transformation_version: str | None = None
    prepared_artifact_digest: str | None = None
    loader_version: str | None = None

    def __post_init__(self):
        if not self.source_url.strip():
            raise ValueError("source_url is required")
        if self.download_timestamp.utcoffset() is None:
            raise ValueError("download_timestamp must include a timezone")
        for digest in (self.sha256, self.schema_digest, self.prepared_artifact_digest):
            if digest is not None and re.fullmatch(r"[0-9a-f]{64}", digest) is None:
                raise ValueError("Digests must be lowercase SHA256 hex strings")
        for count in (self.file_size, self.row_count):
            if count is not None and (type(count) is not int or count < 0):
                raise ValueError("Sizes and row counts must be nonnegative integers")

    def to_dict(self) -> dict:
        value = asdict(self)
        value["download_timestamp"] = self.download_timestamp.isoformat()
        return value

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, indent=2) + "\n"

    @classmethod
    def from_dict(cls, value: dict):
        fields = dict(value)
        fields["download_timestamp"] = datetime.fromisoformat(fields["download_timestamp"])
        return cls(**fields)
