"""Pydantic output models for all AI agent stages."""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class TierConditionCriterion(BaseModel):
    """A single criterion within a tier condition."""

    metric: str  # ADAV | ADRV | ADV | NBBO_PCT | TOTAL_VOLUME | CCV_PCT | CROSS_ASSET
    capacities: list[str] = Field(default_factory=list)
    security_filter: str | None = None
    operator: str  # >= | <= | > | <
    value: float
    unit: str  # PCT_OCV | PCT_CCV | PCT_TCV | CONTRACTS | PERCENT
    description: str = ""


class TierCondition(BaseModel):
    """Structured tier condition with AND/OR logic."""

    logic: str = "AND"  # AND | OR
    criteria: list[TierConditionCriterion] = Field(default_factory=list)


class ExtractedFee(BaseModel):
    """Single fee entry extracted by AI.

    V3 fields (new schema — per-exchange prompts):
    """

    # --- V3 Identity ---
    fee_id: str | None = None
    fee_name: str | None = None

    # --- V3 Origin ---
    origin_code: str | None = None
    contra_origin_code: str | None = None

    # --- V3 Product Dimensions ---
    product_type: str | None = None
    contra_product_type: str | None = None
    listing_type: str | None = None
    penny_class: str | None = None
    multi_listed: bool | None = None
    symbol: str | None = None

    # --- V3 Execution Type (layered) ---
    exec_venue: str | None = None
    liquidity_role: str | None = None
    auction_type: str | None = None
    auction_role: str | None = None

    # --- V3 Fee Value ---
    fee_value: float | None = None
    is_rebate: bool = False

    # --- V3 Fee Unit (shared field name with V2, different semantics) ---
    fee_type: str | None = None

    # --- V3 Tiers ---
    tier_level: int | None = None
    tier_condition: str | None = None

    # --- Legacy V2 fields (kept for backward compat during migration) ---
    fee_code: str | None = None
    participant_type: str | None = None
    contra_party_type: str | None = None
    security_class: str | None = None
    order_type: str | None = None
    fee_unit: str = "PER_CONTRACT"
    amount: float | None = None
    routing_destination: str | None = None
    tier_group: str | None = None
    tier_number: int | None = None
    tier_conditions: TierCondition | None = None
    conditions: dict | None = None
    section_ref: str | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def validate_amount(self) -> "ExtractedFee":
        # V3 validation
        if self.fee_value is not None and self.fee_type == "PER_CONTRACT" and abs(self.fee_value) > 10.0:
            raise ValueError(
                f"Amount ${self.fee_value} exceeds $10/contract — likely an error. "
                f"If this is a flat/monthly fee, set fee_type to 'MONTHLY' or 'FLAT'."
            )
        # Legacy V2 validation
        if self.amount is not None and self.fee_unit == "PER_CONTRACT" and abs(self.amount) > 10.0:
            raise ValueError(
                f"Amount ${self.amount} exceeds $10/contract — likely an error. "
                f"If this is a flat/monthly fee, set fee_unit to 'MONTHLY' or 'FLAT'."
            )
        return self


class SectionExtractionResult(BaseModel):
    """Result of extracting fees from one section or the full document."""

    exchange_name: str = ""
    effective_date: str | None = None
    fees: list[ExtractedFee] = Field(default_factory=list)
    extraction_notes: str = ""


class TableClassification(BaseModel):
    """AI classification of a single table."""

    table_index: int
    is_fee_table: bool
    table_type: str = "OTHER"  # FEE_TRANSACTION | DEFINITIONS | CONNECTIVITY | OTHER
    confidence: float = 1.0
    reasoning: str = ""


class ValidationIssue(BaseModel):
    """A single issue found during validation."""

    severity: str = "WARNING"  # ERROR | WARNING | INFO
    category: str = ""  # MISSING_PARTICIPANT | MISSING_FEE_TYPE | AMOUNT_OUTLIER | ...
    message: str = ""
    affected_indices: list[int] = Field(default_factory=list)


class ValidationResult(BaseModel):
    """Result of fee validation."""

    is_valid: bool = True
    confidence: float = 0.0
    issues: list[ValidationIssue] = Field(default_factory=list)
    suggested_actions: list[str] = Field(default_factory=list)


class CorrectionResult(BaseModel):
    """Result of targeted correction."""

    corrections: list[ExtractedFee] = Field(default_factory=list)
    removed_indices: list[int] = Field(default_factory=list)
    confidence: float = 0.0
    notes: str = ""


class ExtractionPlan(BaseModel):
    """Orchestrator's plan for how to extract fees from the document."""

    needs_sectioned_extraction: bool = False
    section_count: int = 0
    estimated_fee_count: int = 0
    strategy_notes: str = ""


class OrchestratorResult(BaseModel):
    """Final result from the orchestrator agent — the merged extraction."""

    exchange_name: str = ""
    effective_date: str | None = None
    fees: list[ExtractedFee] = Field(default_factory=list)
    extraction_notes: str = ""
    validation_confidence: float = 0.0


class UrlEvaluationResult(BaseModel):
    """Result of URL discovery evaluation."""

    primary_url: str | None = None
    alternate_urls: list[str] = Field(default_factory=list)
    recommended_format: str = "HTML"
    confidence: float = 0.0
    reasoning: str = ""


class ChangeSummary(BaseModel):
    """AI-generated summary of fee changes."""

    summary: str = ""
    impact_level: str = "LOW"  # HIGH | MEDIUM | LOW
    key_changes: list[str] = Field(default_factory=list)
