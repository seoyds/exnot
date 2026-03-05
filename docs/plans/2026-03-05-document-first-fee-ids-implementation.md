# Document-First Architecture + Canonical Fee IDs Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make documents first-class entities with admin review workflows, add canonical fee identifiers and billing code capture, and enhance discovery to classify all document types.

**Architecture:** New `ExchangeDocument` model with lifecycle (DISCOVERED→CLASSIFIED→APPROVED→REJECTED→STALE). New `CanonicalFee` reference table + `BillingCode` table. Enhanced discovery pipeline classifies all found URLs. Dashboard gets a documents review page. Scrape pipeline queries approved documents instead of raw Exchange URLs.

**Tech Stack:** SQLAlchemy 2.x (async), Alembic, PydanticAI agents, FastAPI + Jinja2 + HTMX + Tailwind, Celery

---

## Task 1: Database Models — New Enums and ExchangeDocument

**Files:**
- Modify: `src/exnot/db/models.py` (after line 173, add new enums; after line 439, add new model)
- Create: `tests/unit/test_exchange_document_model.py`

**Step 1: Write the failing test**

```python
# tests/unit/test_exchange_document_model.py
from exnot.db.models import (
    DocumentCategory,
    DocumentStatus,
    ExchangeDocument,
)


def test_document_category_enum_values():
    assert DocumentCategory.FEE_SCHEDULE.value == "FEE_SCHEDULE"
    assert DocumentCategory.PROTOCOL_SPEC.value == "PROTOCOL_SPEC"
    assert DocumentCategory.REGULATORY_FILING.value == "REGULATORY_FILING"
    assert DocumentCategory.MEMBERSHIP_AGREEMENT.value == "MEMBERSHIP_AGREEMENT"
    assert DocumentCategory.CIRCULAR_NOTICE.value == "CIRCULAR_NOTICE"
    assert DocumentCategory.OTHER.value == "OTHER"


def test_document_status_enum_values():
    assert DocumentStatus.DISCOVERED.value == "DISCOVERED"
    assert DocumentStatus.CLASSIFIED.value == "CLASSIFIED"
    assert DocumentStatus.APPROVED.value == "APPROVED"
    assert DocumentStatus.REJECTED.value == "REJECTED"
    assert DocumentStatus.STALE.value == "STALE"


def test_exchange_document_table_name():
    assert ExchangeDocument.__tablename__ == "exchange_documents"


def test_exchange_document_has_required_columns():
    col_names = {c.name for c in ExchangeDocument.__table__.columns}
    required = {
        "id", "exchange_id", "source_url", "url_pattern", "title",
        "content_type", "doc_category", "status", "is_pinned", "is_primary",
        "classification_confidence", "classification_reasoning", "admin_notes",
        "last_seen_at", "last_fetched_hash", "discovered_at", "approved_at",
        "approved_by", "created_at", "updated_at",
    }
    assert required.issubset(col_names)
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_exchange_document_model.py -v`
Expected: FAIL with `ImportError: cannot import name 'DocumentCategory'`

**Step 3: Write minimal implementation**

Add to `src/exnot/db/models.py` after the `AgentEventType` enum (after line 173):

```python
class DocumentCategory(enum.Enum):
    FEE_SCHEDULE = "FEE_SCHEDULE"
    PROTOCOL_SPEC = "PROTOCOL_SPEC"
    REGULATORY_FILING = "REGULATORY_FILING"
    MEMBERSHIP_AGREEMENT = "MEMBERSHIP_AGREEMENT"
    CIRCULAR_NOTICE = "CIRCULAR_NOTICE"
    OTHER = "OTHER"


class DocumentStatus(enum.Enum):
    DISCOVERED = "DISCOVERED"
    CLASSIFIED = "CLASSIFIED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    STALE = "STALE"


class BillingProtocol(enum.Enum):
    FIX = "FIX"
    BINARY = "BINARY"
    SRO = "SRO"
    OTHER = "OTHER"
```

Add the `ExchangeDocument` model after `DiscoveryLog` (after line 439):

```python
class ExchangeDocument(Base):
    __tablename__ = "exchange_documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    exchange_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("exchanges.id"), index=True)
    source_url: Mapped[str] = mapped_column(String(500))
    url_pattern: Mapped[str | None] = mapped_column(String(500), nullable=True)
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    content_type: Mapped[str] = mapped_column(String(50))
    doc_category: Mapped[DocumentCategory] = mapped_column(Enum(DocumentCategory), default=DocumentCategory.OTHER)
    status: Mapped[DocumentStatus] = mapped_column(Enum(DocumentStatus), default=DocumentStatus.DISCOVERED)
    is_pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    classification_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    classification_reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    admin_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_fetched_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    discovered_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now)

    exchange: Mapped["Exchange"] = relationship(back_populates="documents")
    approver: Mapped["User"] = relationship()
```

Add `documents` relationship to the `Exchange` model (after line 205):

```python
    documents: Mapped[list["ExchangeDocument"]] = relationship(back_populates="exchange", cascade="all, delete-orphan")
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_exchange_document_model.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/exnot/db/models.py tests/unit/test_exchange_document_model.py
git commit -m "feat: add ExchangeDocument model with lifecycle enums"
```

---

## Task 2: Database Models — CanonicalFee and BillingCode

**Files:**
- Modify: `src/exnot/db/models.py` (add two new models after ExchangeDocument)
- Modify: `src/exnot/db/models.py` (add new columns to NormalizedFee around line 234)
- Create: `tests/unit/test_canonical_fee_model.py`

**Step 1: Write the failing test**

```python
# tests/unit/test_canonical_fee_model.py
from exnot.db.models import (
    BillingCode,
    BillingProtocol,
    CanonicalFee,
    NormalizedFee,
)


def test_canonical_fee_table_name():
    assert CanonicalFee.__tablename__ == "canonical_fees"


def test_canonical_fee_has_required_columns():
    col_names = {c.name for c in CanonicalFee.__table__.columns}
    required = {"id", "canonical_code", "display_name", "fee_type", "description", "category"}
    assert required.issubset(col_names)


def test_billing_code_table_name():
    assert BillingCode.__tablename__ == "billing_codes"


def test_billing_code_has_required_columns():
    col_names = {c.name for c in BillingCode.__table__.columns}
    required = {
        "id", "exchange_id", "code", "protocol", "description",
        "canonical_fee_id", "source_document_id", "effective_date", "tag_number",
    }
    assert required.issubset(col_names)


def test_billing_protocol_enum():
    assert BillingProtocol.FIX.value == "FIX"
    assert BillingProtocol.BINARY.value == "BINARY"


def test_normalized_fee_has_canonical_fee_id():
    col_names = {c.name for c in NormalizedFee.__table__.columns}
    assert "canonical_fee_id" in col_names
    assert "exchange_fee_code" in col_names
    assert "exchange_fee_name" in col_names
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_canonical_fee_model.py -v`
Expected: FAIL with `ImportError: cannot import name 'CanonicalFee'`

**Step 3: Write minimal implementation**

Add `CanonicalFee` model after `ExchangeDocument`:

```python
class CanonicalFee(Base):
    __tablename__ = "canonical_fees"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    canonical_code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(100))
    fee_type: Mapped[FeeType] = mapped_column(Enum(FeeType))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(String(50), nullable=True)
```

Add `BillingCode` model after `CanonicalFee`:

```python
class BillingCode(Base):
    __tablename__ = "billing_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    exchange_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("exchanges.id"), index=True)
    code: Mapped[str] = mapped_column(String(50))
    protocol: Mapped[BillingProtocol] = mapped_column(Enum(BillingProtocol), default=BillingProtocol.OTHER)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    canonical_fee_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("canonical_fees.id"), nullable=True)
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("exchange_documents.id"), nullable=True)
    effective_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    tag_number: Mapped[int | None] = mapped_column(Integer, nullable=True)

    exchange: Mapped["Exchange"] = relationship()
    canonical_fee: Mapped["CanonicalFee"] = relationship()
    source_document: Mapped["ExchangeDocument"] = relationship()
```

Add new columns to `NormalizedFee` (around line 290, after existing V3 fields):

```python
    # Canonical fee mapping
    canonical_fee_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("canonical_fees.id"), nullable=True)
    exchange_fee_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    exchange_fee_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_canonical_fee_model.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/exnot/db/models.py tests/unit/test_canonical_fee_model.py
git commit -m "feat: add CanonicalFee, BillingCode models and NormalizedFee extensions"
```

---

## Task 3: Alembic Migration

**Files:**
- Create: new migration file via autogenerate

**Step 1: Generate migration**

```bash
alembic revision --autogenerate -m "add exchange_documents canonical_fees billing_codes tables"
```

**Step 2: Review the generated migration**

Open the generated file in `alembic/versions/` and verify it creates:
- `exchange_documents` table with all columns
- `canonical_fees` table with all columns
- `billing_codes` table with all columns
- Adds `canonical_fee_id`, `exchange_fee_code`, `exchange_fee_name` columns to `normalized_fees`
- Creates proper foreign keys and indexes

**Step 3: Run migration**

```bash
alembic upgrade head
```

**Step 4: Verify migration applied**

```bash
alembic current
```

**Step 5: Commit**

```bash
git add alembic/versions/*.py
git commit -m "feat: migration for exchange_documents, canonical_fees, billing_codes"
```

---

## Task 4: Canonical Fee Seed Data

**Files:**
- Create: `src/exnot/exchanges/canonical_fees.yml`
- Create: `tests/unit/test_canonical_fees_seed.py`
- Modify: `src/exnot/exchanges/registry.py` (add loader function)

**Step 1: Write the failing test**

```python
# tests/unit/test_canonical_fees_seed.py
import yaml
from pathlib import Path


def test_canonical_fees_yaml_exists():
    path = Path(__file__).parent.parent.parent / "src" / "exnot" / "exchanges" / "canonical_fees.yml"
    assert path.exists()


def test_canonical_fees_yaml_structure():
    path = Path(__file__).parent.parent.parent / "src" / "exnot" / "exchanges" / "canonical_fees.yml"
    data = yaml.safe_load(path.read_text())
    assert "fees" in data
    assert len(data["fees"]) >= 20

    first = data["fees"][0]
    assert "canonical_code" in first
    assert "display_name" in first
    assert "fee_type" in first
    assert "category" in first


def test_canonical_codes_are_unique():
    path = Path(__file__).parent.parent.parent / "src" / "exnot" / "exchanges" / "canonical_fees.yml"
    data = yaml.safe_load(path.read_text())
    codes = [f["canonical_code"] for f in data["fees"]]
    assert len(codes) == len(set(codes)), f"Duplicate codes found: {[c for c in codes if codes.count(c) > 1]}"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_canonical_fees_seed.py -v`
Expected: FAIL with `AssertionError` (file doesn't exist)

**Step 3: Create canonical fees seed file**

```yaml
# src/exnot/exchanges/canonical_fees.yml
fees:
  # Transaction fees - Maker/Taker
  - canonical_code: MAKER_REBATE
    display_name: "Maker Rebate"
    fee_type: MAKER
    category: transaction
    description: "Rebate for providing liquidity (adding to the book)"
  - canonical_code: MAKER_FEE
    display_name: "Maker Fee"
    fee_type: MAKER
    category: transaction
    description: "Fee for providing liquidity (when no rebate applies)"
  - canonical_code: TAKER_FEE
    display_name: "Taker Fee"
    fee_type: TAKER
    category: transaction
    description: "Fee for removing liquidity (taking from the book)"
  - canonical_code: TAKER_REBATE
    display_name: "Taker Rebate"
    fee_type: TAKER
    category: transaction
    description: "Rebate for removing liquidity (inverted market)"

  # Routing
  - canonical_code: ROUTING_FEE
    display_name: "Routing Fee"
    fee_type: ROUTING
    category: routing
    description: "Fee for orders routed to other exchanges"
  - canonical_code: ROUTING_REBATE
    display_name: "Routing Rebate"
    fee_type: ROUTING
    category: routing
    description: "Rebate for routed orders"

  # Regulatory
  - canonical_code: OPTIONS_REGULATORY_FEE
    display_name: "Options Regulatory Fee (ORF)"
    fee_type: ORF
    category: regulatory
    description: "Per-contract regulatory fee assessed by all options exchanges"

  # Transaction
  - canonical_code: TRANSACTION_FEE
    display_name: "Transaction Fee"
    fee_type: TRANSACTION
    category: transaction
    description: "General per-contract transaction fee"
  - canonical_code: CLEARING_FEE
    display_name: "Clearing Fee"
    fee_type: CLEARING
    category: clearing
    description: "Per-contract clearing fee"

  # Auction
  - canonical_code: CROSSING_FEE
    display_name: "Crossing Fee"
    fee_type: CROSSING_FEE
    category: auction
    description: "Fee for crossing/matched orders in auction mechanism"
  - canonical_code: PIM_FEE
    display_name: "Price Improvement Mechanism Fee"
    fee_type: PIM_FEE
    category: auction
    description: "Fee for Price Improvement Mechanism (PIM) orders"
  - canonical_code: PIM_REBATE
    display_name: "PIM Rebate"
    fee_type: PIM_FEE
    category: auction
    description: "Rebate for PIM responses"
  - canonical_code: RESPONSE_FEE
    display_name: "Auction Response Fee"
    fee_type: RESPONSE_FEE
    category: auction
    description: "Fee for responding to auction notifications (SAL, AIM, etc.)"
  - canonical_code: BREAK_UP_REBATE
    display_name: "Break-Up Rebate"
    fee_type: BREAK_UP_REBATE
    category: auction
    description: "Rebate when auction is broken up by competing orders"

  # Surcharges
  - canonical_code: SURCHARGE
    display_name: "Surcharge"
    fee_type: SURCHARGE
    category: surcharge
    description: "Additional surcharge on top of base fee"
  - canonical_code: INDEX_SURCHARGE
    display_name: "Index Options Surcharge"
    fee_type: SURCHARGE
    category: surcharge
    description: "Additional surcharge for index options"
  - canonical_code: COMPLEX_SURCHARGE
    display_name: "Complex Order Surcharge"
    fee_type: SURCHARGE
    category: surcharge
    description: "Additional surcharge for complex/multi-leg orders"

  # Connectivity and access
  - canonical_code: CONNECTIVITY_FEE
    display_name: "Connectivity Fee"
    fee_type: CONNECTIVITY
    category: connectivity
    description: "Monthly port/connectivity fee"
  - canonical_code: MARKET_DATA_FEE
    display_name: "Market Data Fee"
    fee_type: MARKET_DATA
    category: market_data
    description: "Fee for market data feeds"
  - canonical_code: MEMBERSHIP_FEE
    display_name: "Membership Fee"
    fee_type: MEMBERSHIP
    category: membership
    description: "Trading permit/membership fee"

  # Cancellation
  - canonical_code: CANCELLATION_FEE
    display_name: "Cancellation Fee"
    fee_type: CANCELLATION
    category: cancellation
    description: "Fee for order cancellations exceeding thresholds"

  # Stock handling
  - canonical_code: STOCK_HANDLING_FEE
    display_name: "Stock Handling Fee"
    fee_type: STOCK_HANDLING
    category: execution
    description: "Fee for stock leg of buy-write or stock-option orders"

  # Complex-specific maker/taker
  - canonical_code: COMPLEX_MAKER_REBATE
    display_name: "Complex Order Maker Rebate"
    fee_type: MAKER
    category: transaction
    description: "Maker rebate specific to complex/multi-leg orders"
  - canonical_code: COMPLEX_TAKER_FEE
    display_name: "Complex Order Taker Fee"
    fee_type: TAKER
    category: transaction
    description: "Taker fee specific to complex/multi-leg orders"

  # Directed order
  - canonical_code: DIRECTED_ORDER_FEE
    display_name: "Directed Order Fee"
    fee_type: TAKER
    category: transaction
    description: "Fee for orders directed to a specific market maker"

  # QCC
  - canonical_code: QCC_FEE
    display_name: "Qualified Contingent Cross Fee"
    fee_type: CROSSING_FEE
    category: auction
    description: "Fee for Qualified Contingent Cross transactions"

  # FLEX
  - canonical_code: FLEX_FEE
    display_name: "FLEX Options Fee"
    fee_type: TRANSACTION
    category: transaction
    description: "Fee for FLEX options transactions"
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_canonical_fees_seed.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/exnot/exchanges/canonical_fees.yml tests/unit/test_canonical_fees_seed.py
git commit -m "feat: add canonical fee seed data (27 entries)"
```

---

## Task 5: Repository Layer — ExchangeDocumentRepository

**Files:**
- Modify: `src/exnot/db/repositories.py` (add new repository class after `ScrapedDocumentRepository`)
- Create: `tests/unit/test_document_repository.py`

**Step 1: Write the failing test**

```python
# tests/unit/test_document_repository.py
from exnot.db.repositories import ExchangeDocumentRepository


def test_exchange_document_repository_exists():
    """Verify the class exists and has the expected methods."""
    assert hasattr(ExchangeDocumentRepository, "get_by_exchange")
    assert hasattr(ExchangeDocumentRepository, "get_approved_for_exchange")
    assert hasattr(ExchangeDocumentRepository, "get_pinned_for_exchange")
    assert hasattr(ExchangeDocumentRepository, "get_pending_review")
    assert hasattr(ExchangeDocumentRepository, "get_by_url")
    assert hasattr(ExchangeDocumentRepository, "create")
    assert hasattr(ExchangeDocumentRepository, "update_status")
    assert hasattr(ExchangeDocumentRepository, "upsert_by_url")
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_document_repository.py -v`
Expected: FAIL with `ImportError`

**Step 3: Write implementation**

Add to `src/exnot/db/repositories.py` after `ScrapedDocumentRepository`:

```python
class ExchangeDocumentRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_exchange(
        self,
        exchange_id: uuid.UUID,
        category: DocumentCategory | None = None,
        status: DocumentStatus | None = None,
    ) -> list[ExchangeDocument]:
        stmt = select(ExchangeDocument).where(ExchangeDocument.exchange_id == exchange_id)
        if category:
            stmt = stmt.where(ExchangeDocument.doc_category == category)
        if status:
            stmt = stmt.where(ExchangeDocument.status == status)
        stmt = stmt.order_by(
            ExchangeDocument.is_pinned.desc(),
            ExchangeDocument.is_primary.desc(),
            ExchangeDocument.discovered_at.desc(),
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_approved_for_exchange(
        self, exchange_id: uuid.UUID, category: DocumentCategory | None = None
    ) -> list[ExchangeDocument]:
        return await self.get_by_exchange(exchange_id, category=category, status=DocumentStatus.APPROVED)

    async def get_pinned_for_exchange(self, exchange_id: uuid.UUID) -> list[ExchangeDocument]:
        stmt = (
            select(ExchangeDocument)
            .where(
                ExchangeDocument.exchange_id == exchange_id,
                ExchangeDocument.is_pinned == True,
                ExchangeDocument.status == DocumentStatus.APPROVED,
            )
            .order_by(ExchangeDocument.is_primary.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_pending_review(self, exchange_id: uuid.UUID | None = None) -> list[ExchangeDocument]:
        stmt = select(ExchangeDocument).where(ExchangeDocument.status == DocumentStatus.CLASSIFIED)
        if exchange_id:
            stmt = stmt.where(ExchangeDocument.exchange_id == exchange_id)
        stmt = stmt.order_by(ExchangeDocument.discovered_at.desc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_url(self, exchange_id: uuid.UUID, source_url: str) -> ExchangeDocument | None:
        stmt = select(ExchangeDocument).where(
            ExchangeDocument.exchange_id == exchange_id,
            ExchangeDocument.source_url == source_url,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(self, doc: ExchangeDocument) -> ExchangeDocument:
        self.session.add(doc)
        await self.session.flush()
        return doc

    async def update_status(
        self,
        doc_id: uuid.UUID,
        status: DocumentStatus,
        approved_by: uuid.UUID | None = None,
        admin_notes: str | None = None,
    ) -> ExchangeDocument | None:
        stmt = select(ExchangeDocument).where(ExchangeDocument.id == doc_id)
        result = await self.session.execute(stmt)
        doc = result.scalar_one_or_none()
        if doc:
            doc.status = status
            if status == DocumentStatus.APPROVED and approved_by:
                doc.approved_at = datetime.utcnow()
                doc.approved_by = approved_by
            if admin_notes is not None:
                doc.admin_notes = admin_notes
            await self.session.flush()
        return doc

    async def upsert_by_url(
        self,
        exchange_id: uuid.UUID,
        source_url: str,
        defaults: dict,
    ) -> tuple[ExchangeDocument, bool]:
        """Insert or update by exchange_id+source_url. Returns (doc, created)."""
        existing = await self.get_by_url(exchange_id, source_url)
        if existing:
            for key, val in defaults.items():
                if hasattr(existing, key):
                    setattr(existing, key, val)
            existing.last_seen_at = datetime.utcnow()
            await self.session.flush()
            return existing, False
        doc = ExchangeDocument(exchange_id=exchange_id, source_url=source_url, **defaults)
        self.session.add(doc)
        await self.session.flush()
        return doc, True
```

Add necessary imports at top of `repositories.py`:
```python
from exnot.db.models import ExchangeDocument, DocumentCategory, DocumentStatus, CanonicalFee, BillingCode
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_document_repository.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/exnot/db/repositories.py tests/unit/test_document_repository.py
git commit -m "feat: add ExchangeDocumentRepository with lifecycle methods"
```

---

## Task 6: Repository Layer — CanonicalFeeRepository and BillingCodeRepository

**Files:**
- Modify: `src/exnot/db/repositories.py`
- Create: `tests/unit/test_canonical_fee_repository.py`

**Step 1: Write the failing test**

```python
# tests/unit/test_canonical_fee_repository.py
from exnot.db.repositories import CanonicalFeeRepository, BillingCodeRepository


def test_canonical_fee_repository_exists():
    assert hasattr(CanonicalFeeRepository, "get_all")
    assert hasattr(CanonicalFeeRepository, "get_by_code")
    assert hasattr(CanonicalFeeRepository, "seed_from_yaml")


def test_billing_code_repository_exists():
    assert hasattr(BillingCodeRepository, "get_by_exchange")
    assert hasattr(BillingCodeRepository, "upsert")
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_canonical_fee_repository.py -v`
Expected: FAIL

**Step 3: Write implementation**

Add to `src/exnot/db/repositories.py`:

```python
class CanonicalFeeRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_all(self) -> list[CanonicalFee]:
        stmt = select(CanonicalFee).order_by(CanonicalFee.category, CanonicalFee.canonical_code)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_code(self, canonical_code: str) -> CanonicalFee | None:
        stmt = select(CanonicalFee).where(CanonicalFee.canonical_code == canonical_code)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id(self, fee_id: int) -> CanonicalFee | None:
        stmt = select(CanonicalFee).where(CanonicalFee.id == fee_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def seed_from_yaml(self, yaml_path: str) -> int:
        """Load canonical fees from YAML, upsert by canonical_code. Returns count of new entries."""
        import yaml
        from pathlib import Path

        data = yaml.safe_load(Path(yaml_path).read_text())
        created = 0
        for entry in data["fees"]:
            existing = await self.get_by_code(entry["canonical_code"])
            if not existing:
                fee = CanonicalFee(
                    canonical_code=entry["canonical_code"],
                    display_name=entry["display_name"],
                    fee_type=FeeType[entry["fee_type"]],
                    description=entry.get("description"),
                    category=entry.get("category"),
                )
                self.session.add(fee)
                created += 1
        await self.session.flush()
        return created


class BillingCodeRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_exchange(self, exchange_id: uuid.UUID) -> list[BillingCode]:
        stmt = (
            select(BillingCode)
            .where(BillingCode.exchange_id == exchange_id)
            .order_by(BillingCode.code)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def upsert(self, exchange_id: uuid.UUID, code: str, defaults: dict) -> tuple[BillingCode, bool]:
        stmt = select(BillingCode).where(
            BillingCode.exchange_id == exchange_id,
            BillingCode.code == code,
        )
        result = await self.session.execute(stmt)
        existing = result.scalar_one_or_none()
        if existing:
            for key, val in defaults.items():
                if hasattr(existing, key):
                    setattr(existing, key, val)
            await self.session.flush()
            return existing, False
        billing_code = BillingCode(exchange_id=exchange_id, code=code, **defaults)
        self.session.add(billing_code)
        await self.session.flush()
        return billing_code, True
```

**Step 4: Run tests**

Run: `pytest tests/unit/test_canonical_fee_repository.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/exnot/db/repositories.py tests/unit/test_canonical_fee_repository.py
git commit -m "feat: add CanonicalFeeRepository and BillingCodeRepository"
```

---

## Task 7: Document Classification Agent

**Files:**
- Create: `src/exnot/ai/agents/doc_classifier.py`
- Modify: `src/exnot/ai/types.py` (add `DocumentClassificationResult` output model)
- Modify: `src/exnot/ai/deps.py` (add `ClassificationDeps` if needed, or reuse `DiscoveryDeps`)
- Modify: `src/exnot/config.py` (add `ai_model_doc_classification` setting)
- Create: `tests/unit/test_doc_classifier_types.py`

**Step 1: Write the failing test**

```python
# tests/unit/test_doc_classifier_types.py
from exnot.ai.types import DocumentClassificationResult


def test_doc_classification_result_fields():
    result = DocumentClassificationResult(
        doc_category="FEE_SCHEDULE",
        confidence=0.95,
        reasoning="Contains fee schedule tables with per-contract pricing",
    )
    assert result.doc_category == "FEE_SCHEDULE"
    assert result.confidence == 0.95
    assert result.reasoning


def test_doc_classification_result_valid_categories():
    valid = {"FEE_SCHEDULE", "PROTOCOL_SPEC", "REGULATORY_FILING", "MEMBERSHIP_AGREEMENT", "CIRCULAR_NOTICE", "OTHER"}
    for cat in valid:
        result = DocumentClassificationResult(doc_category=cat, confidence=0.5, reasoning="test")
        assert result.doc_category == cat
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_doc_classifier_types.py -v`
Expected: FAIL with `ImportError`

**Step 3: Write implementation**

Add to `src/exnot/ai/types.py` (after `ChangeSummary`, around line 178):

```python
class DocumentClassificationResult(BaseModel):
    """AI classification of a discovered document."""
    doc_category: str  # One of DocumentCategory values
    confidence: float
    reasoning: str
```

Add to `src/exnot/config.py` (after `ai_model_change_summary`, around line 71):

```python
    ai_model_doc_classification: str = "qwen/qwen3.5-flash"
    doc_auto_approve_threshold: float = 0.9
    discovery_include_protocol_specs: bool = True
    ai_model_protocol_extraction: str = "qwen/qwen3.5-flash"
```

Create `src/exnot/ai/agents/doc_classifier.py`:

```python
"""Document classification agent — categorizes discovered URLs into document types."""

from pydantic_ai import Agent, ToolOutput

from exnot.ai.deps import DiscoveryDeps
from exnot.ai.types import DocumentClassificationResult

doc_classifier_agent = Agent[DiscoveryDeps, DocumentClassificationResult](
    "test",
    deps_type=DiscoveryDeps,
    output_type=ToolOutput(DocumentClassificationResult, name="return_classification"),
    instructions=(
        "You are a document classifier for US options exchanges. "
        "Given a URL, title, and content preview, classify the document into one of these categories:\n"
        "- FEE_SCHEDULE: Fee schedule, pricing schedule, or fee table document\n"
        "- PROTOCOL_SPEC: FIX protocol specification, binary order entry spec, or technical interface document\n"
        "- REGULATORY_FILING: SEC filing, rule change, regulatory submission\n"
        "- MEMBERSHIP_AGREEMENT: Membership application, trading permit, connectivity agreement\n"
        "- CIRCULAR_NOTICE: Exchange circular, regulatory circular, fee change notice, information memo\n"
        "- OTHER: Does not fit any category above\n\n"
        "Return your classification with a confidence score (0.0-1.0) and brief reasoning."
    ),
    retries=1,
)
```

**Step 4: Run tests**

Run: `pytest tests/unit/test_doc_classifier_types.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/exnot/ai/agents/doc_classifier.py src/exnot/ai/types.py src/exnot/config.py tests/unit/test_doc_classifier_types.py
git commit -m "feat: add document classification agent and output types"
```

---

## Task 8: Enhanced Discovery — Classify All Documents

**Files:**
- Modify: `src/exnot/discovery/discoverer.py` (add classification step after probing)
- Modify: `src/exnot/discovery/pipeline.py` (store ExchangeDocument records instead of just updating Exchange)
- Create: `tests/unit/test_discovery_classification.py`

**Step 1: Write the failing test**

```python
# tests/unit/test_discovery_classification.py
from exnot.discovery.discoverer import UrlDiscoverer, ClassifiedCandidate


def test_classified_candidate_dataclass():
    cc = ClassifiedCandidate(
        url="https://example.com/fee_schedule.pdf",
        title="Fee Schedule",
        content_type="PDF",
        doc_category="FEE_SCHEDULE",
        classification_confidence=0.95,
        classification_reasoning="Contains fee tables",
        content_preview="Fee Schedule...",
        is_pdf=True,
        is_csv=False,
    )
    assert cc.doc_category == "FEE_SCHEDULE"
    assert cc.classification_confidence == 0.95


def test_discoverer_has_classify_method():
    assert hasattr(UrlDiscoverer, "_classify_candidates")
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_discovery_classification.py -v`
Expected: FAIL

**Step 3: Write implementation**

Add `ClassifiedCandidate` dataclass to `src/exnot/discovery/discoverer.py` (after `CandidateUrl`, around line 27):

```python
@dataclass
class ClassifiedCandidate:
    url: str
    title: str
    content_type: str
    doc_category: str  # DocumentCategory value
    classification_confidence: float
    classification_reasoning: str
    content_preview: str = ""
    is_pdf: bool = False
    is_csv: bool = False
```

Add `_classify_candidates` method to `UrlDiscoverer`:

```python
    async def _classify_candidates(self, candidates: list[CandidateUrl]) -> list[ClassifiedCandidate]:
        """Classify each candidate URL into a document category using AI."""
        from exnot.ai.agents.doc_classifier import doc_classifier_agent
        from exnot.ai.deps import DiscoveryDeps
        from exnot.ai.models import get_model
        from exnot.config import get_settings

        settings = get_settings()
        model = get_model(settings.ai_model_doc_classification)
        classified = []

        for candidate in candidates:
            try:
                prompt = (
                    f"URL: {candidate.url}\n"
                    f"Title: {candidate.title}\n"
                    f"Content Type: {candidate.content_type}\n"
                    f"Preview: {candidate.content_preview[:500] if candidate.content_preview else 'N/A'}\n"
                )
                deps = DiscoveryDeps(exchange_code="", exchange_name="", operator="")
                result = await doc_classifier_agent.run(prompt, model=model, deps=deps)
                classified.append(ClassifiedCandidate(
                    url=candidate.url,
                    title=candidate.title,
                    content_type=candidate.content_type or ("PDF" if candidate.is_pdf else "HTML"),
                    doc_category=result.output.doc_category,
                    classification_confidence=result.output.confidence,
                    classification_reasoning=result.output.reasoning,
                    content_preview=candidate.content_preview or "",
                    is_pdf=candidate.is_pdf,
                    is_csv=candidate.is_csv,
                ))
            except Exception:
                classified.append(ClassifiedCandidate(
                    url=candidate.url,
                    title=candidate.title,
                    content_type=candidate.content_type or "HTML",
                    doc_category="OTHER",
                    classification_confidence=0.0,
                    classification_reasoning="Classification failed",
                    content_preview=candidate.content_preview or "",
                    is_pdf=candidate.is_pdf,
                    is_csv=candidate.is_csv,
                ))

        return classified
```

Update `DiscoveryResult` dataclass to include classified candidates:

```python
# Add field to DiscoveryResult
    classified_candidates: list[ClassifiedCandidate] = field(default_factory=list)
```

Update the `discover()` method to call `_classify_candidates` after probing and include results in `DiscoveryResult`.

Modify `_build_search_queries` to include protocol spec queries when `settings.discovery_include_protocol_specs` is True:

```python
        if get_settings().discovery_include_protocol_specs:
            queries.append(f'"{exchange_name}" FIX protocol specification options')
```

**Step 4: Run tests**

Run: `pytest tests/unit/test_discovery_classification.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/exnot/discovery/discoverer.py tests/unit/test_discovery_classification.py
git commit -m "feat: add document classification to discovery pipeline"
```

---

## Task 9: Discovery Pipeline — Store ExchangeDocument Records

**Files:**
- Modify: `src/exnot/discovery/pipeline.py` (create ExchangeDocument records from classified candidates)
- Create: `tests/unit/test_discovery_pipeline_docs.py`

**Step 1: Write the failing test**

```python
# tests/unit/test_discovery_pipeline_docs.py
from exnot.discovery.pipeline import _create_exchange_documents


def test_create_exchange_documents_function_exists():
    """Verify the function that creates ExchangeDocument records from classified candidates exists."""
    assert callable(_create_exchange_documents)
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_discovery_pipeline_docs.py -v`
Expected: FAIL

**Step 3: Write implementation**

Add to `src/exnot/discovery/pipeline.py`:

```python
def _create_exchange_documents(exchange, classified_candidates, session):
    """Create or update ExchangeDocument records from classified candidates.

    Uses sync session (same as run_discovery_pipeline).
    Auto-approves high-confidence fee schedule docs.
    """
    from exnot.db.models import ExchangeDocument, DocumentCategory, DocumentStatus
    from exnot.config import get_settings

    settings = get_settings()
    threshold = settings.doc_auto_approve_threshold
    created_docs = []

    for candidate in classified_candidates:
        # Check if already exists
        existing = session.query(ExchangeDocument).filter_by(
            exchange_id=exchange.id,
            source_url=candidate.url,
        ).first()

        if existing:
            existing.last_seen_at = datetime.utcnow()
            existing.classification_confidence = candidate.classification_confidence
            existing.classification_reasoning = candidate.classification_reasoning
            if existing.status == DocumentStatus.DISCOVERED:
                existing.status = DocumentStatus.CLASSIFIED
                existing.doc_category = DocumentCategory[candidate.doc_category]
            created_docs.append(existing)
            continue

        doc_category = DocumentCategory[candidate.doc_category]
        status = DocumentStatus.CLASSIFIED

        # Auto-approve high-confidence fee schedule docs
        if doc_category == DocumentCategory.FEE_SCHEDULE and candidate.classification_confidence >= threshold:
            status = DocumentStatus.APPROVED

        doc = ExchangeDocument(
            exchange_id=exchange.id,
            source_url=candidate.url,
            title=candidate.title,
            content_type=candidate.content_type,
            doc_category=doc_category,
            status=status,
            classification_confidence=candidate.classification_confidence,
            classification_reasoning=candidate.classification_reasoning,
            discovered_at=datetime.utcnow(),
            last_seen_at=datetime.utcnow(),
        )
        session.add(doc)
        created_docs.append(doc)

    session.flush()
    return created_docs
```

Update `run_discovery_pipeline` to call `_create_exchange_documents` with classified candidates.

**Step 4: Run tests**

Run: `pytest tests/unit/test_discovery_pipeline_docs.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/exnot/discovery/pipeline.py tests/unit/test_discovery_pipeline_docs.py
git commit -m "feat: store ExchangeDocument records from discovery pipeline"
```

---

## Task 10: URL Pattern Derivation

**Files:**
- Create: `src/exnot/discovery/url_patterns.py`
- Create: `tests/unit/test_url_patterns.py`

**Step 1: Write the failing test**

```python
# tests/unit/test_url_patterns.py
from exnot.discovery.url_patterns import derive_url_pattern, match_url_pattern


def test_derive_pattern_from_pdf_url():
    url = "https://www.nyse.com/publicdocs/nyse/markets/nyse-arca/NYSE_Arca_Options_Fee_Schedule.pdf"
    pattern = derive_url_pattern(url)
    assert pattern is not None
    assert "nyse.com" in pattern
    assert "fee" in pattern.lower() or "Fee" in pattern


def test_derive_pattern_from_html_url():
    url = "https://www.cboe.com/us/options/membership/fee_schedule/"
    pattern = derive_url_pattern(url)
    assert pattern is not None
    assert "cboe.com" in pattern


def test_match_url_pattern():
    pattern = derive_url_pattern("https://www.nyse.com/publicdocs/nyse/markets/nyse-arca/NYSE_Arca_Options_Fee_Schedule.pdf")
    assert match_url_pattern(pattern, "https://www.nyse.com/publicdocs/nyse/markets/nyse-arca/NYSE_Arca_Options_Fee_Schedule.pdf")


def test_match_pattern_with_version_change():
    pattern = derive_url_pattern("https://exchange.com/docs/fee_schedule_2025.pdf")
    assert match_url_pattern(pattern, "https://exchange.com/docs/fee_schedule_2026.pdf")


def test_no_match_different_domain():
    pattern = derive_url_pattern("https://exchange.com/docs/fee_schedule.pdf")
    assert not match_url_pattern(pattern, "https://other.com/docs/fee_schedule.pdf")
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_url_patterns.py -v`
Expected: FAIL

**Step 3: Write implementation**

```python
# src/exnot/discovery/url_patterns.py
"""URL pattern derivation and matching for pinned document URLs."""

import re
from urllib.parse import urlparse


def derive_url_pattern(url: str) -> str | None:
    """Derive a regex pattern from a URL that matches structurally similar URLs.

    Replaces date-like segments (2024, 2025, etc.) and version numbers with wildcards.
    Keeps domain, path structure, and file extension stable.
    """
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return None

    # Escape the domain for regex
    domain_pattern = re.escape(parsed.netloc)

    # Process path: replace year-like numbers and version strings with wildcards
    path = parsed.path
    # Replace 4-digit years (2020-2030 range)
    path_pattern = re.sub(r"20[2-3]\d", r"20[2-3]\\d", re.escape(path))
    # Replace version-like patterns (v1, v2.3, etc.)
    path_pattern = re.sub(r"v\d+(\.\d+)*", r"v\\d+(\\.\\d+)*", path_pattern)

    return f"^https?://{domain_pattern}{path_pattern}"


def match_url_pattern(pattern: str | None, url: str) -> bool:
    """Check if a URL matches a derived pattern."""
    if not pattern:
        return False
    try:
        return bool(re.match(pattern, url))
    except re.error:
        return False
```

**Step 4: Run tests**

Run: `pytest tests/unit/test_url_patterns.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/exnot/discovery/url_patterns.py tests/unit/test_url_patterns.py
git commit -m "feat: add URL pattern derivation and matching for pinned documents"
```

---

## Task 11: Scrape Pipeline — Use ExchangeDocuments

**Files:**
- Modify: `src/exnot/workers/pipelines.py` (update `run_scrape_pipeline` to query ExchangeDocument)
- Create: `tests/unit/test_pipeline_doc_lookup.py`

**Step 1: Write the failing test**

```python
# tests/unit/test_pipeline_doc_lookup.py
from exnot.workers.pipelines import _get_approved_document_urls


def test_get_approved_document_urls_exists():
    assert callable(_get_approved_document_urls)
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_pipeline_doc_lookup.py -v`
Expected: FAIL

**Step 3: Write implementation**

Add helper to `src/exnot/workers/pipelines.py`:

```python
def _get_approved_document_urls(exchange, session) -> tuple[str, list[str]]:
    """Get approved document URLs for an exchange.

    Returns (primary_url, alternate_urls).
    Priority: pinned docs > approved fee schedule docs > Exchange.fee_schedule_url fallback.
    Uses sync session (same as pipeline).
    """
    from exnot.db.models import ExchangeDocument, DocumentCategory, DocumentStatus

    # 1. Check pinned documents
    pinned = (
        session.query(ExchangeDocument)
        .filter_by(exchange_id=exchange.id, is_pinned=True, status=DocumentStatus.APPROVED)
        .order_by(ExchangeDocument.is_primary.desc())
        .all()
    )
    if pinned:
        primary_url = pinned[0].source_url
        alternate_urls = [d.source_url for d in pinned[1:]]
        return primary_url, alternate_urls

    # 2. Check approved fee schedule documents
    approved = (
        session.query(ExchangeDocument)
        .filter_by(
            exchange_id=exchange.id,
            doc_category=DocumentCategory.FEE_SCHEDULE,
            status=DocumentStatus.APPROVED,
        )
        .order_by(ExchangeDocument.is_primary.desc(), ExchangeDocument.classification_confidence.desc())
        .all()
    )
    if approved:
        primary_url = approved[0].source_url
        alternate_urls = [d.source_url for d in approved[1:]]
        return primary_url, alternate_urls

    # 3. Fallback to Exchange.fee_schedule_url
    return exchange.fee_schedule_url, exchange.alternate_urls or []
```

Update `run_scrape_pipeline` to call `_get_approved_document_urls` and use the returned URLs instead of directly using `exchange.fee_schedule_url`. The key change is around line 107 where `_collect_documents` is called — pass the resolved URLs instead of the exchange object directly.

Also add stale URL detection: if a pinned URL returns 404, mark the `ExchangeDocument.status = STALE` and try pattern matching via `match_url_pattern`.

**Step 4: Run tests**

Run: `pytest tests/unit/test_pipeline_doc_lookup.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/exnot/workers/pipelines.py tests/unit/test_pipeline_doc_lookup.py
git commit -m "feat: pipeline uses ExchangeDocument for URL resolution with fallback"
```

---

## Task 12: Pipeline — Save Canonical Fee Mappings and Billing Codes

**Files:**
- Modify: `src/exnot/workers/pipelines.py` (update `_save_normalized_fees` to include canonical fee mapping)
- Modify: `src/exnot/ai/types.py` (add `exchange_fee_code`, `exchange_fee_name`, `suggested_canonical_code` to `ExtractedFee`)
- Create: `tests/unit/test_canonical_fee_mapping.py`

**Step 1: Write the failing test**

```python
# tests/unit/test_canonical_fee_mapping.py
from exnot.ai.types import ExtractedFee


def test_extracted_fee_has_canonical_fields():
    fee = ExtractedFee(
        participant_type="CUSTOMER",
        security_class="PENNY",
        order_type="SIMPLE",
        fee_type="MAKER",
        amount=-0.25,
        exchange_fee_code="OB",
        exchange_fee_name="Options Base Rate",
        suggested_canonical_code="MAKER_REBATE",
    )
    assert fee.exchange_fee_code == "OB"
    assert fee.exchange_fee_name == "Options Base Rate"
    assert fee.suggested_canonical_code == "MAKER_REBATE"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_canonical_fee_mapping.py -v`
Expected: FAIL (fields don't exist yet on ExtractedFee)

**Step 3: Write implementation**

Add fields to `ExtractedFee` in `src/exnot/ai/types.py` (around line 80, with the V3 fields):

```python
    # Fee identity fields
    exchange_fee_code: str | None = None
    exchange_fee_name: str | None = None
    suggested_canonical_code: str | None = None
```

Update `_save_normalized_fees` in `src/exnot/workers/pipelines.py` (around line 629) to map these new fields:

```python
        # In the NormalizedFee creation (inside the loop):
        exchange_fee_code=fee_entry.exchange_fee_code if hasattr(fee_entry, 'exchange_fee_code') else fee_entry.fee_code,
        exchange_fee_name=fee_entry.exchange_fee_name if hasattr(fee_entry, 'exchange_fee_name') else fee_entry.fee_name,
```

Add canonical fee ID lookup: after saving normalized fees, match `suggested_canonical_code` against `CanonicalFee` table and set `canonical_fee_id`.

**Step 4: Run tests**

Run: `pytest tests/unit/test_canonical_fee_mapping.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/exnot/ai/types.py src/exnot/workers/pipelines.py tests/unit/test_canonical_fee_mapping.py
git commit -m "feat: canonical fee mapping in extraction and pipeline save"
```

---

## Task 13: Dashboard — Documents Page Template

**Files:**
- Create: `src/exnot/dashboard/templates/documents.html`

**Step 1: Create the template**

```html
{% extends "base.html" %}

{% block title %}{{ exchange.name }} — Documents{% endblock %}

{% block header %}
<div class="flex items-center justify-between">
    <div>
        <a href="/dashboard/exchanges/{{ exchange.code }}" class="text-blue-600 hover:text-blue-800 text-sm">← Back to {{ exchange.name }}</a>
        <h1 class="text-2xl font-bold text-slate-900 mt-1">Documents — {{ exchange.name }}</h1>
        <p class="text-sm text-slate-500">{{ documents | length }} documents discovered</p>
    </div>
</div>
{% endblock %}

{% block content %}
<div class="max-w-5xl mx-auto space-y-6">

    {# Filters #}
    <div class="flex gap-3 items-center flex-wrap">
        <select id="filter-category" onchange="filterDocuments()" class="rounded-lg border-slate-300 text-sm px-3 py-1.5">
            <option value="">All Categories</option>
            <option value="FEE_SCHEDULE">Fee Schedule</option>
            <option value="PROTOCOL_SPEC">Protocol Spec</option>
            <option value="REGULATORY_FILING">Regulatory Filing</option>
            <option value="MEMBERSHIP_AGREEMENT">Membership Agreement</option>
            <option value="CIRCULAR_NOTICE">Circular/Notice</option>
            <option value="OTHER">Other</option>
        </select>
        <select id="filter-status" onchange="filterDocuments()" class="rounded-lg border-slate-300 text-sm px-3 py-1.5">
            <option value="">All Statuses</option>
            <option value="APPROVED">Approved</option>
            <option value="CLASSIFIED">Pending Review</option>
            <option value="REJECTED">Rejected</option>
            <option value="STALE">Stale</option>
        </select>
    </div>

    {# Approved & Pinned section #}
    {% set approved_docs = documents | selectattr("status.value", "equalto", "APPROVED") | list %}
    {% if approved_docs %}
    <div class="space-y-3">
        <h2 class="text-lg font-semibold text-green-700 flex items-center gap-2">
            <span class="w-2 h-2 rounded-full bg-green-500"></span> Approved ({{ approved_docs | length }})
        </h2>
        {% for doc in approved_docs %}
        <div class="doc-card bg-white border border-green-200 rounded-lg p-4 shadow-sm" data-category="{{ doc.doc_category.value }}" data-status="{{ doc.status.value }}">
            <div class="flex items-start justify-between gap-4">
                <div class="flex-1 min-w-0">
                    <div class="flex items-center gap-2 mb-1">
                        {% if doc.is_pinned %}<span class="text-xs bg-blue-100 text-blue-700 px-2 py-0.5 rounded-full font-medium">Pinned</span>{% endif %}
                        {% if doc.is_primary %}<span class="text-xs bg-green-100 text-green-700 px-2 py-0.5 rounded-full font-medium">Primary</span>{% endif %}
                        <span class="text-xs bg-slate-100 text-slate-600 px-2 py-0.5 rounded-full">{{ doc.content_type }}</span>
                        <span class="text-xs bg-slate-100 text-slate-600 px-2 py-0.5 rounded-full">{{ doc.doc_category.value | replace("_", " ") | title }}</span>
                    </div>
                    <p class="text-sm font-medium text-slate-900 truncate">{{ doc.title or doc.source_url | truncate(80) }}</p>
                    <p class="text-xs text-slate-500 truncate mt-0.5">{{ doc.source_url }}</p>
                    <p class="text-xs text-slate-400 mt-1">
                        Confidence: {{ "%.0f" | format(doc.classification_confidence * 100 if doc.classification_confidence else 0) }}%
                        · Last seen: {{ doc.last_seen_at.strftime('%Y-%m-%d %H:%M') if doc.last_seen_at else 'Never' }}
                        {% if doc.last_fetched_hash %} · Hash: {{ doc.last_fetched_hash[:8] }}...{% endif %}
                    </p>
                </div>
                <div class="flex gap-2 shrink-0">
                    {% if user and user.is_admin %}
                    {% if doc.is_pinned %}
                    <form method="post" action="/dashboard/exchanges/{{ exchange.code }}/documents/{{ doc.id }}/unpin">
                        <button type="submit" class="text-xs px-3 py-1.5 rounded-lg border border-slate-300 text-slate-600 hover:bg-slate-50">Unpin</button>
                    </form>
                    {% else %}
                    <form method="post" action="/dashboard/exchanges/{{ exchange.code }}/documents/{{ doc.id }}/pin">
                        <button type="submit" class="text-xs px-3 py-1.5 rounded-lg border border-blue-300 text-blue-600 hover:bg-blue-50">Pin</button>
                    </form>
                    {% endif %}
                    <form method="post" action="/dashboard/exchanges/{{ exchange.code }}/documents/{{ doc.id }}/reject">
                        <button type="submit" class="text-xs px-3 py-1.5 rounded-lg border border-red-300 text-red-600 hover:bg-red-50">Reject</button>
                    </form>
                    {% endif %}
                    <a href="{{ doc.source_url }}" target="_blank" class="text-xs px-3 py-1.5 rounded-lg border border-slate-300 text-slate-600 hover:bg-slate-50">View</a>
                </div>
            </div>
            {% if doc.admin_notes %}
            <p class="text-xs text-slate-500 mt-2 italic">Note: {{ doc.admin_notes }}</p>
            {% endif %}
        </div>
        {% endfor %}
    </div>
    {% endif %}

    {# Pending Review section #}
    {% set pending_docs = documents | selectattr("status.value", "equalto", "CLASSIFIED") | list %}
    {% if pending_docs %}
    <div class="space-y-3">
        <h2 class="text-lg font-semibold text-amber-700 flex items-center gap-2">
            <span class="w-2 h-2 rounded-full bg-amber-500"></span> Pending Review ({{ pending_docs | length }})
        </h2>
        {% for doc in pending_docs %}
        <div class="doc-card bg-white border border-amber-200 rounded-lg p-4 shadow-sm" data-category="{{ doc.doc_category.value }}" data-status="{{ doc.status.value }}">
            <div class="flex items-start justify-between gap-4">
                <div class="flex-1 min-w-0">
                    <div class="flex items-center gap-2 mb-1">
                        <span class="text-xs bg-slate-100 text-slate-600 px-2 py-0.5 rounded-full">{{ doc.content_type }}</span>
                        <span class="text-xs bg-amber-100 text-amber-700 px-2 py-0.5 rounded-full">{{ doc.doc_category.value | replace("_", " ") | title }}</span>
                        <span class="text-xs text-slate-400">{{ "%.0f" | format(doc.classification_confidence * 100 if doc.classification_confidence else 0) }}% confidence</span>
                    </div>
                    <p class="text-sm font-medium text-slate-900 truncate">{{ doc.title or doc.source_url | truncate(80) }}</p>
                    <p class="text-xs text-slate-500 truncate mt-0.5">{{ doc.source_url }}</p>
                    {% if doc.classification_reasoning %}
                    <p class="text-xs text-slate-500 mt-1 italic">AI: {{ doc.classification_reasoning | truncate(120) }}</p>
                    {% endif %}
                </div>
                <div class="flex gap-2 shrink-0">
                    {% if user and user.is_admin %}
                    <form method="post" action="/dashboard/exchanges/{{ exchange.code }}/documents/{{ doc.id }}/approve">
                        <button type="submit" class="text-xs px-3 py-1.5 rounded-lg bg-green-600 text-white hover:bg-green-700">Approve</button>
                    </form>
                    <form method="post" action="/dashboard/exchanges/{{ exchange.code }}/documents/{{ doc.id }}/approve-pin">
                        <button type="submit" class="text-xs px-3 py-1.5 rounded-lg bg-blue-600 text-white hover:bg-blue-700">Approve & Pin</button>
                    </form>
                    <form method="post" action="/dashboard/exchanges/{{ exchange.code }}/documents/{{ doc.id }}/reject">
                        <button type="submit" class="text-xs px-3 py-1.5 rounded-lg border border-red-300 text-red-600 hover:bg-red-50">Reject</button>
                    </form>
                    {% endif %}
                    <a href="{{ doc.source_url }}" target="_blank" class="text-xs px-3 py-1.5 rounded-lg border border-slate-300 text-slate-600 hover:bg-slate-50">View</a>
                </div>
            </div>
        </div>
        {% endfor %}
    </div>
    {% endif %}

    {# Rejected section (collapsed by default) #}
    {% set rejected_docs = documents | selectattr("status.value", "equalto", "REJECTED") | list %}
    {% if rejected_docs %}
    <details class="space-y-3">
        <summary class="text-lg font-semibold text-red-700 flex items-center gap-2 cursor-pointer">
            <span class="w-2 h-2 rounded-full bg-red-500"></span> Rejected ({{ rejected_docs | length }})
        </summary>
        <div class="space-y-3 mt-3">
        {% for doc in rejected_docs %}
        <div class="doc-card bg-white border border-red-100 rounded-lg p-4 shadow-sm opacity-60" data-category="{{ doc.doc_category.value }}" data-status="{{ doc.status.value }}">
            <div class="flex items-start justify-between gap-4">
                <div class="flex-1 min-w-0">
                    <span class="text-xs bg-slate-100 text-slate-600 px-2 py-0.5 rounded-full">{{ doc.doc_category.value | replace("_", " ") | title }}</span>
                    <p class="text-sm text-slate-700 truncate mt-1">{{ doc.title or doc.source_url | truncate(80) }}</p>
                    <p class="text-xs text-slate-400 truncate">{{ doc.source_url }}</p>
                </div>
                <div class="flex gap-2 shrink-0">
                    {% if user and user.is_admin %}
                    <form method="post" action="/dashboard/exchanges/{{ exchange.code }}/documents/{{ doc.id }}/approve">
                        <button type="submit" class="text-xs px-3 py-1.5 rounded-lg border border-green-300 text-green-600 hover:bg-green-50">Restore</button>
                    </form>
                    {% endif %}
                    <a href="{{ doc.source_url }}" target="_blank" class="text-xs px-3 py-1.5 rounded-lg border border-slate-300 text-slate-600 hover:bg-slate-50">View</a>
                </div>
            </div>
        </div>
        {% endfor %}
        </div>
    </details>
    {% endif %}

    {# Stale section #}
    {% set stale_docs = documents | selectattr("status.value", "equalto", "STALE") | list %}
    {% if stale_docs %}
    <div class="space-y-3">
        <h2 class="text-lg font-semibold text-slate-500 flex items-center gap-2">
            <span class="w-2 h-2 rounded-full bg-slate-400"></span> Stale ({{ stale_docs | length }})
        </h2>
        {% for doc in stale_docs %}
        <div class="doc-card bg-white border border-slate-200 rounded-lg p-4 shadow-sm opacity-60" data-category="{{ doc.doc_category.value }}" data-status="{{ doc.status.value }}">
            <p class="text-sm text-slate-600 truncate">{{ doc.title or doc.source_url | truncate(80) }}</p>
            <p class="text-xs text-red-500 mt-1">URL no longer accessible — needs admin review</p>
        </div>
        {% endfor %}
    </div>
    {% endif %}

    {% if not documents %}
    <div class="text-center py-12 text-slate-500">
        <p class="text-lg">No documents discovered yet.</p>
        <p class="text-sm mt-1">Run a scrape to trigger document discovery.</p>
    </div>
    {% endif %}
</div>

<script>
function filterDocuments() {
    const category = document.getElementById('filter-category').value;
    const status = document.getElementById('filter-status').value;
    document.querySelectorAll('.doc-card').forEach(card => {
        const matchCat = !category || card.dataset.category === category;
        const matchStatus = !status || card.dataset.status === status;
        card.style.display = (matchCat && matchStatus) ? '' : 'none';
    });
}
</script>
{% endblock %}
```

**Step 2: Commit**

```bash
git add src/exnot/dashboard/templates/documents.html
git commit -m "feat: add documents dashboard template with admin review UI"
```

---

## Task 14: Dashboard — Documents Routes

**Files:**
- Modify: `src/exnot/dashboard/routes.py` (add GET /documents page + POST action routes)

**Step 1: Write the failing test**

```python
# tests/unit/test_dashboard_doc_routes.py
from exnot.dashboard.routes import router


def test_documents_routes_registered():
    route_paths = [r.path for r in router.routes if hasattr(r, "path")]
    assert "/dashboard/exchanges/{code}/documents" in route_paths
    assert "/dashboard/exchanges/{code}/documents/{doc_id}/approve" in route_paths
    assert "/dashboard/exchanges/{code}/documents/{doc_id}/approve-pin" in route_paths
    assert "/dashboard/exchanges/{code}/documents/{doc_id}/reject" in route_paths
    assert "/dashboard/exchanges/{code}/documents/{doc_id}/pin" in route_paths
    assert "/dashboard/exchanges/{code}/documents/{doc_id}/unpin" in route_paths
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_dashboard_doc_routes.py -v`
Expected: FAIL

**Step 3: Write implementation**

Add to `src/exnot/dashboard/routes.py` (after `exchange_detail` route, around line 210):

```python
@router.get("/dashboard/exchanges/{code}/documents")
async def exchange_documents(request: Request, code: str, db: AsyncSession = Depends(get_db)):
    user = await _get_current_user_from_cookie(request, db)
    exchange_repo = ExchangeRepository(db)
    doc_repo = ExchangeDocumentRepository(db)

    exchange = await exchange_repo.get_by_code(code)
    if not exchange:
        return RedirectResponse("/dashboard", status_code=302)

    documents = await doc_repo.get_by_exchange(exchange.id)

    return templates.TemplateResponse("documents.html", {
        "request": request,
        "exchange": exchange,
        "documents": documents,
        "user": user,
    })


@router.post("/dashboard/exchanges/{code}/documents/{doc_id}/approve")
async def approve_document(request: Request, code: str, doc_id: str, db: AsyncSession = Depends(get_db)):
    user = await _get_current_user_from_cookie(request, db)
    if not user or not user.is_admin:
        return RedirectResponse(f"/dashboard/exchanges/{code}/documents", status_code=302)

    doc_repo = ExchangeDocumentRepository(db)
    await doc_repo.update_status(uuid.UUID(doc_id), DocumentStatus.APPROVED, approved_by=user.id)
    await db.commit()
    return RedirectResponse(f"/dashboard/exchanges/{code}/documents", status_code=302)


@router.post("/dashboard/exchanges/{code}/documents/{doc_id}/approve-pin")
async def approve_and_pin_document(request: Request, code: str, doc_id: str, db: AsyncSession = Depends(get_db)):
    user = await _get_current_user_from_cookie(request, db)
    if not user or not user.is_admin:
        return RedirectResponse(f"/dashboard/exchanges/{code}/documents", status_code=302)

    doc_repo = ExchangeDocumentRepository(db)
    doc = await doc_repo.update_status(uuid.UUID(doc_id), DocumentStatus.APPROVED, approved_by=user.id)
    if doc:
        doc.is_pinned = True
        # Derive URL pattern for future matching
        from exnot.discovery.url_patterns import derive_url_pattern
        doc.url_pattern = derive_url_pattern(doc.source_url)
        await db.flush()
    await db.commit()
    return RedirectResponse(f"/dashboard/exchanges/{code}/documents", status_code=302)


@router.post("/dashboard/exchanges/{code}/documents/{doc_id}/reject")
async def reject_document(request: Request, code: str, doc_id: str, db: AsyncSession = Depends(get_db)):
    user = await _get_current_user_from_cookie(request, db)
    if not user or not user.is_admin:
        return RedirectResponse(f"/dashboard/exchanges/{code}/documents", status_code=302)

    doc_repo = ExchangeDocumentRepository(db)
    await doc_repo.update_status(uuid.UUID(doc_id), DocumentStatus.REJECTED)
    await db.commit()
    return RedirectResponse(f"/dashboard/exchanges/{code}/documents", status_code=302)


@router.post("/dashboard/exchanges/{code}/documents/{doc_id}/pin")
async def pin_document(request: Request, code: str, doc_id: str, db: AsyncSession = Depends(get_db)):
    user = await _get_current_user_from_cookie(request, db)
    if not user or not user.is_admin:
        return RedirectResponse(f"/dashboard/exchanges/{code}/documents", status_code=302)

    doc_repo = ExchangeDocumentRepository(db)
    stmt = select(ExchangeDocument).where(ExchangeDocument.id == uuid.UUID(doc_id))
    result = await db.execute(stmt)
    doc = result.scalar_one_or_none()
    if doc:
        doc.is_pinned = True
        from exnot.discovery.url_patterns import derive_url_pattern
        doc.url_pattern = derive_url_pattern(doc.source_url)
        await db.flush()
    await db.commit()
    return RedirectResponse(f"/dashboard/exchanges/{code}/documents", status_code=302)


@router.post("/dashboard/exchanges/{code}/documents/{doc_id}/unpin")
async def unpin_document(request: Request, code: str, doc_id: str, db: AsyncSession = Depends(get_db)):
    user = await _get_current_user_from_cookie(request, db)
    if not user or not user.is_admin:
        return RedirectResponse(f"/dashboard/exchanges/{code}/documents", status_code=302)

    stmt = select(ExchangeDocument).where(ExchangeDocument.id == uuid.UUID(doc_id))
    result = await db.execute(stmt)
    doc = result.scalar_one_or_none()
    if doc:
        doc.is_pinned = False
        await db.flush()
    await db.commit()
    return RedirectResponse(f"/dashboard/exchanges/{code}/documents", status_code=302)
```

Add necessary imports at top of routes.py:
```python
from exnot.db.models import ExchangeDocument, DocumentStatus
from exnot.db.repositories import ExchangeDocumentRepository
```

**Step 4: Run tests**

Run: `pytest tests/unit/test_dashboard_doc_routes.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/exnot/dashboard/routes.py tests/unit/test_dashboard_doc_routes.py
git commit -m "feat: add dashboard routes for document review (approve/reject/pin)"
```

---

## Task 15: Dashboard — Link Documents Page from Exchange Detail

**Files:**
- Modify: `src/exnot/dashboard/templates/exchange.html` (add "Documents" link/button)
- Modify: `src/exnot/dashboard/templates/dashboard.html` (add pending doc count column)
- Modify: `src/exnot/dashboard/routes.py` (pass pending doc counts to dashboard overview)

**Step 1: Add Documents link to exchange detail template**

In `exchange.html`, add a "Documents" link button near the scrape button area (around line 14):

```html
<a href="/dashboard/exchanges/{{ exchange.code }}/documents"
   class="inline-flex items-center px-4 py-2 text-sm font-medium text-blue-600 bg-blue-50 border border-blue-200 rounded-lg hover:bg-blue-100">
    Documents
    {% if pending_doc_count %}
    <span class="ml-2 bg-amber-500 text-white text-xs rounded-full px-2 py-0.5">{{ pending_doc_count }}</span>
    {% endif %}
</a>
```

**Step 2: Pass pending doc count from exchange_detail route**

In `routes.py`'s `exchange_detail` function, add:

```python
    doc_repo = ExchangeDocumentRepository(db)
    pending_docs = await doc_repo.get_pending_review(exchange.id)
    # Add to template context:
    "pending_doc_count": len(pending_docs),
```

**Step 3: Add doc count to main dashboard table**

In `dashboard.html`, add a "Docs" column to the exchange table showing document count and pending count.

In `routes.py`'s `dashboard_overview`, query document counts per exchange and pass to template.

**Step 4: Commit**

```bash
git add src/exnot/dashboard/templates/exchange.html src/exnot/dashboard/templates/dashboard.html src/exnot/dashboard/routes.py
git commit -m "feat: link documents page from exchange detail and dashboard"
```

---

## Task 16: Display Canonical Fee IDs and Exchange Fee Codes in Dashboard

**Files:**
- Modify: `src/exnot/dashboard/templates/exchange.html` (add fee code columns to fee table)
- Modify: `src/exnot/dashboard/routes.py` (join canonical_fee in query)

**Step 1: Update the fee table in exchange.html**

Add columns for exchange fee code and canonical fee name to the fees table. In the table header:

```html
<th class="px-3 py-2 text-left text-xs font-medium text-slate-500 uppercase">Fee Code</th>
<th class="px-3 py-2 text-left text-xs font-medium text-slate-500 uppercase">Canonical</th>
```

In the table body row:

```html
<td class="px-3 py-2 text-sm text-slate-700">{{ fee.exchange_fee_code or '—' }}</td>
<td class="px-3 py-2 text-sm text-slate-500">
    {% if fee.canonical_fee %}{{ fee.canonical_fee.display_name }}{% else %}—{% endif %}
</td>
```

**Step 2: Update the NormalizedFee query to eager-load canonical_fee**

In `repositories.py`, update `NormalizedFeeRepository.get_by_snapshot` to include:
```python
from sqlalchemy.orm import selectinload
# Add to the select statement:
.options(selectinload(NormalizedFee.canonical_fee))
```

Add the `canonical_fee` relationship to `NormalizedFee` in `db/models.py`:
```python
    canonical_fee: Mapped["CanonicalFee | None"] = relationship()
```

**Step 3: Commit**

```bash
git add src/exnot/dashboard/templates/exchange.html src/exnot/db/models.py src/exnot/db/repositories.py
git commit -m "feat: display exchange fee codes and canonical fee names in dashboard"
```

---

## Task 17: Comparison Page — Use Canonical Fee IDs

**Files:**
- Modify: `src/exnot/dashboard/templates/comparison.html` (add canonical fee column)
- Modify: `src/exnot/dashboard/routes.py` (include canonical fees in comparison data)

**Step 1: Update comparison route to include canonical fee data**

In the `compare_page` route, ensure the comparison query joins `CanonicalFee`. Group fees by `canonical_fee_id` in addition to existing dimensions so that the same fee concept across exchanges aligns properly.

**Step 2: Update comparison template**

Add a "Canonical Fee" column to the comparison table. When fees from different exchanges share the same `canonical_fee_id`, highlight them as "matched" to show cross-exchange equivalence.

**Step 3: Commit**

```bash
git add src/exnot/dashboard/templates/comparison.html src/exnot/dashboard/routes.py
git commit -m "feat: cross-exchange comparison using canonical fee IDs"
```

---

## Task 18: Protocol Spec Extraction Agent (Billing Codes)

**Files:**
- Create: `src/exnot/ai/agents/protocol_extractor.py`
- Modify: `src/exnot/ai/types.py` (add `ProtocolExtractionResult`)
- Create: `tests/unit/test_protocol_extractor_types.py`

**Step 1: Write the failing test**

```python
# tests/unit/test_protocol_extractor_types.py
from exnot.ai.types import ProtocolExtractionResult, ExtractedBillingCode


def test_extracted_billing_code():
    code = ExtractedBillingCode(
        code="OB",
        protocol="FIX",
        description="Options Base transaction",
        tag_number=20116,
        fee_type_hint="MAKER",
    )
    assert code.code == "OB"
    assert code.tag_number == 20116


def test_protocol_extraction_result():
    result = ProtocolExtractionResult(
        billing_codes=[
            ExtractedBillingCode(code="OB", protocol="FIX", description="Options Base")
        ],
        extraction_notes="Found 1 billing code in FIX spec",
    )
    assert len(result.billing_codes) == 1
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_protocol_extractor_types.py -v`
Expected: FAIL

**Step 3: Write implementation**

Add to `src/exnot/ai/types.py`:

```python
class ExtractedBillingCode(BaseModel):
    """A billing code extracted from a protocol specification document."""
    code: str
    protocol: str = "OTHER"  # FIX, BINARY, SRO, OTHER
    description: str | None = None
    tag_number: int | None = None
    fee_type_hint: str | None = None  # Suggested FeeType mapping


class ProtocolExtractionResult(BaseModel):
    """Result of parsing a protocol spec document for billing codes."""
    billing_codes: list[ExtractedBillingCode]
    extraction_notes: str = ""
```

Create `src/exnot/ai/agents/protocol_extractor.py`:

```python
"""Protocol specification extraction agent — extracts billing codes from FIX/binary specs."""

from pydantic_ai import Agent, ToolOutput

from exnot.ai.deps import DiscoveryDeps
from exnot.ai.types import ProtocolExtractionResult

protocol_extractor_agent = Agent[DiscoveryDeps, ProtocolExtractionResult](
    "test",
    deps_type=DiscoveryDeps,
    output_type=ToolOutput(ProtocolExtractionResult, name="return_billing_codes"),
    instructions=(
        "You are a billing code extractor for US options exchange protocol specifications. "
        "Given text from a FIX protocol or binary order entry specification document, "
        "extract all billing codes, transaction type codes, and fee-related identifiers.\n\n"
        "For each code, provide:\n"
        "- code: The billing/transaction code string\n"
        "- protocol: FIX, BINARY, SRO, or OTHER\n"
        "- description: What this code represents\n"
        "- tag_number: The FIX tag number if applicable (e.g., tag 20116)\n"
        "- fee_type_hint: The most likely FeeType this maps to "
        "(MAKER, TAKER, ROUTING, ORF, TRANSACTION, CLEARING, etc.)\n\n"
        "Focus on codes related to transaction fees, rebates, and billing. "
        "Ignore purely routing or session-level protocol codes."
    ),
    retries=1,
)
```

**Step 4: Run tests**

Run: `pytest tests/unit/test_protocol_extractor_types.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/exnot/ai/agents/protocol_extractor.py src/exnot/ai/types.py tests/unit/test_protocol_extractor_types.py
git commit -m "feat: add protocol spec extraction agent for billing codes"
```

---

## Task 19: Integration — Process Approved Protocol Specs in Pipeline

**Files:**
- Modify: `src/exnot/workers/pipelines.py` (add step to process PROTOCOL_SPEC documents)

**Step 1: Add protocol spec processing to pipeline**

After the main fee extraction/normalization steps in `run_scrape_pipeline`, add a new step that:

1. Queries approved `PROTOCOL_SPEC` documents for the exchange
2. For each, fetches the document content
3. Parses it with the appropriate parser (PDF/HTML)
4. Runs `protocol_extractor_agent` to extract billing codes
5. Saves `BillingCode` records via `BillingCodeRepository`

```python
def _process_protocol_specs(exchange, session, emitter):
    """Process approved protocol spec documents to extract billing codes."""
    from exnot.db.models import ExchangeDocument, DocumentCategory, DocumentStatus, BillingCode, BillingProtocol
    from exnot.ai.agents.protocol_extractor import protocol_extractor_agent
    from exnot.ai.deps import DiscoveryDeps
    from exnot.ai.models import get_model
    from exnot.config import get_settings

    settings = get_settings()

    protocol_docs = (
        session.query(ExchangeDocument)
        .filter_by(
            exchange_id=exchange.id,
            doc_category=DocumentCategory.PROTOCOL_SPEC,
            status=DocumentStatus.APPROVED,
        )
        .all()
    )

    if not protocol_docs:
        return

    model = get_model(settings.ai_model_protocol_extraction)

    for doc in protocol_docs:
        try:
            # Fetch and parse the document
            collection_result = asyncio.run(_fetch_single_document(doc.source_url))
            if not collection_result:
                continue

            parsed = _parse_document_content(collection_result)
            if not parsed:
                continue

            deps = DiscoveryDeps(
                exchange_code=exchange.code,
                exchange_name=exchange.name,
                operator=exchange.operator,
            )
            result = asyncio.run(protocol_extractor_agent.run(parsed.text[:15000], model=model, deps=deps))

            # Save billing codes
            for bc in result.output.billing_codes:
                existing = session.query(BillingCode).filter_by(
                    exchange_id=exchange.id, code=bc.code
                ).first()
                if not existing:
                    billing_code = BillingCode(
                        exchange_id=exchange.id,
                        code=bc.code,
                        protocol=BillingProtocol[bc.protocol] if bc.protocol in BillingProtocol.__members__ else BillingProtocol.OTHER,
                        description=bc.description,
                        source_document_id=doc.id,
                        tag_number=bc.tag_number,
                    )
                    session.add(billing_code)

            session.flush()

        except Exception as e:
            if emitter:
                emitter.emit_error(f"Protocol spec processing failed for {doc.source_url}: {e}")
```

Call `_process_protocol_specs(exchange, session, emitter)` from `run_scrape_pipeline` after the normalization step (around line 270).

**Step 2: Commit**

```bash
git add src/exnot/workers/pipelines.py
git commit -m "feat: process approved protocol specs for billing code extraction"
```

---

## Task 20: Seed Canonical Fees on Startup

**Files:**
- Modify: `src/exnot/api/app.py` (add canonical fee seeding to startup)

**Step 1: Add seeding to app startup**

In the FastAPI `lifespan` or `startup` event, after exchange seeding, add:

```python
    # Seed canonical fees
    from exnot.db.repositories import CanonicalFeeRepository
    from pathlib import Path

    canonical_fees_path = Path(__file__).parent.parent / "exchanges" / "canonical_fees.yml"
    if canonical_fees_path.exists():
        async with async_session() as session:
            repo = CanonicalFeeRepository(session)
            count = await repo.seed_from_yaml(str(canonical_fees_path))
            if count:
                await session.commit()
                logger.info(f"Seeded {count} new canonical fees")
```

**Step 2: Commit**

```bash
git add src/exnot/api/app.py
git commit -m "feat: seed canonical fees on app startup"
```

---

## Task 21: Migrate Existing fee_code/fee_name Data

**Files:**
- Create: `scripts/migrate_fee_codes.py` (one-time data migration script)

**Step 1: Create migration script**

```python
"""One-time migration: copy NormalizedFee.fee_code → exchange_fee_code, fee_name → exchange_fee_name."""

import asyncio
from sqlalchemy import select, update
from exnot.db.engine import async_session
from exnot.db.models import NormalizedFee


async def migrate():
    async with async_session() as session:
        # Copy fee_code → exchange_fee_code where exchange_fee_code is null
        stmt = (
            update(NormalizedFee)
            .where(NormalizedFee.exchange_fee_code.is_(None))
            .where(NormalizedFee.fee_code.isnot(None))
            .values(exchange_fee_code=NormalizedFee.fee_code)
        )
        result = await session.execute(stmt)
        print(f"Migrated {result.rowcount} fee_code → exchange_fee_code")

        # Copy fee_name → exchange_fee_name where exchange_fee_name is null
        stmt = (
            update(NormalizedFee)
            .where(NormalizedFee.exchange_fee_name.is_(None))
            .where(NormalizedFee.fee_name.isnot(None))
            .values(exchange_fee_name=NormalizedFee.fee_name)
        )
        result = await session.execute(stmt)
        print(f"Migrated {result.rowcount} fee_name → exchange_fee_name")

        await session.commit()
        print("Migration complete.")


if __name__ == "__main__":
    asyncio.run(migrate())
```

**Step 2: Commit**

```bash
git add scripts/migrate_fee_codes.py
git commit -m "feat: add one-time migration script for fee_code → exchange_fee_code"
```

---

## Task 22: Run All Tests and Lint

**Step 1: Run linter**

```bash
ruff check src/ tests/
ruff format src/ tests/
```

Fix any lint issues.

**Step 2: Run all unit tests**

```bash
pytest tests/unit/ -v
```

Fix any failures.

**Step 3: Commit fixes if any**

```bash
git add -u
git commit -m "fix: lint and test fixes for document-first architecture"
```

---

## Task Summary

| Task | Description | New Files | Modified Files |
|------|-------------|-----------|----------------|
| 1 | ExchangeDocument model + enums | test_exchange_document_model.py | db/models.py |
| 2 | CanonicalFee + BillingCode models | test_canonical_fee_model.py | db/models.py |
| 3 | Alembic migration | alembic/versions/*.py | — |
| 4 | Canonical fee seed data | canonical_fees.yml, test | — |
| 5 | ExchangeDocumentRepository | test_document_repository.py | db/repositories.py |
| 6 | CanonicalFee + BillingCode repos | test_canonical_fee_repository.py | db/repositories.py |
| 7 | Doc classification agent | doc_classifier.py, test | ai/types.py, config.py |
| 8 | Discovery classification | test_discovery_classification.py | discovery/discoverer.py |
| 9 | Discovery stores ExchangeDocuments | test_discovery_pipeline_docs.py | discovery/pipeline.py |
| 10 | URL pattern derivation | url_patterns.py, test | — |
| 11 | Pipeline uses ExchangeDocuments | test_pipeline_doc_lookup.py | workers/pipelines.py |
| 12 | Canonical fee mapping in pipeline | test_canonical_fee_mapping.py | ai/types.py, pipelines.py |
| 13 | Documents page template | documents.html | — |
| 14 | Documents dashboard routes | test_dashboard_doc_routes.py | dashboard/routes.py |
| 15 | Link docs page from exchange | — | exchange.html, dashboard.html, routes.py |
| 16 | Display fee codes in dashboard | — | exchange.html, models.py, repos.py |
| 17 | Comparison with canonical IDs | — | comparison.html, routes.py |
| 18 | Protocol spec extraction agent | protocol_extractor.py, test | ai/types.py |
| 19 | Process protocol specs in pipeline | — | workers/pipelines.py |
| 20 | Seed canonical fees on startup | — | api/app.py |
| 21 | Data migration script | migrate_fee_codes.py | — |
| 22 | Lint + test pass | — | various |
