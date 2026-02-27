import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class ContentType(str, Enum):
    PDF = "application/pdf"
    HTML = "text/html"
    CSV = "text/csv"
    EXCEL = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    UNKNOWN = "unknown"


# Priority used to pick the best format for AI extraction (higher = preferred).
FORMAT_PRIORITY: dict[ContentType, int] = {
    ContentType.CSV: 3,
    ContentType.PDF: 2,
    ContentType.HTML: 1,
    ContentType.EXCEL: 1,
    ContentType.UNKNOWN: 0,
}


@dataclass
class DocumentResult:
    content_bytes: bytes
    content_type: ContentType
    source_url: str
    content_hash: str = ""
    fetched_at: datetime = field(default_factory=datetime.utcnow)
    response_headers: dict = field(default_factory=dict)
    status_code: int = 200

    def __post_init__(self):
        if not self.content_hash:
            self.content_hash = hashlib.sha256(self.content_bytes).hexdigest()

    @property
    def text(self) -> str:
        return self.content_bytes.decode("utf-8", errors="replace")

    @property
    def is_pdf(self) -> bool:
        return self.content_type == ContentType.PDF or self.content_bytes[:5] == b"%PDF-"

    @property
    def is_csv(self) -> bool:
        return self.content_type == ContentType.CSV

    @property
    def filename_extension(self) -> str:
        mapping = {
            ContentType.PDF: ".pdf",
            ContentType.HTML: ".html",
            ContentType.CSV: ".csv",
            ContentType.EXCEL: ".xlsx",
        }
        return mapping.get(self.content_type, ".bin")


@dataclass(frozen=True)
class CollectionResult:
    """All documents collected for a single exchange scrape."""

    documents: tuple[DocumentResult, ...]
    primary: DocumentResult

    @property
    def primary_hash(self) -> str:
        return self.primary.content_hash


class AbstractScraper(ABC):
    @abstractmethod
    async def fetch(self, url: str) -> DocumentResult:
        """Fetch a document from the given URL."""
        ...

    @abstractmethod
    async def close(self):
        """Clean up any resources."""
        ...
