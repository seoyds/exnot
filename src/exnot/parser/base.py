from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ExtractedTable:
    """A table extracted from a document."""

    headers: list[str]
    rows: list[list[str]]
    title: str = ""
    page_number: int | None = None
    footnotes: list[str] = field(default_factory=list)


@dataclass
class ExtractedDocument:
    """Full text and tables extracted from a document."""

    full_text: str
    tables: list[ExtractedTable]
    page_count: int = 0
    metadata: dict = field(default_factory=dict)


class AbstractParser(ABC):
    @abstractmethod
    def extract(self, content: bytes) -> ExtractedDocument:
        """Extract text and tables from document content."""
        ...
