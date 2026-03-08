"""Dashboard web routes using FastAPI + Jinja2 + HTMX."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exnot.config import get_settings
from exnot.db.engine import get_db
from exnot.db.models import (
    ChangeType,
    DocumentStatus,
    FeeType,
    NormalizedFee,
    NotificationFrequency,
    OrderType,
    ParticipantType,
    SecurityClass,
    Subscriber,
    User,
)
from exnot.db.repositories import (
    ExchangeDocumentRepository,
    ExchangeRepository,
    FeeChangeRepository,
    NormalizedFeeRepository,
    ScrapedDocumentRepository,
    ScrapeLogRepository,
    SnapshotRepository,
    SubscriberRepository,
    UserRepository,
)

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(tags=["dashboard"])

ALGORITHM = "HS256"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _format_file_size(size_bytes: int) -> str:
    """Convert bytes to a human-readable size string (KB/MB)."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"


def _cents_to_dollars(amount_cents: int | None) -> str:
    """Convert amount in hundredths-of-a-cent to a human-readable dollar string."""
    if amount_cents is None:
        return "N/A"
    amount = Decimal(amount_cents) / Decimal(10000)
    return f"${amount:,.4f}"


async def _get_current_user_from_cookie(
    request: Request,
    db: AsyncSession,
) -> User | None:
    """Extract the logged-in user from the session cookie, if present."""
    token = request.cookies.get("access_token")
    if not token:
        return None
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
        email: str | None = payload.get("sub")
        if email is None:
            return None
    except JWTError:
        return None
    repo = UserRepository(db)
    return await repo.get_by_email(email)


# ---------------------------------------------------------------------------
# Dashboard overview
# ---------------------------------------------------------------------------


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_overview(request: Request, db: AsyncSession = Depends(get_db)):
    """Main dashboard showing all exchanges and recent changes."""
    exchange_repo = ExchangeRepository(db)
    exchanges = await exchange_repo.get_all(active_only=False)

    snapshot_repo = SnapshotRepository(db)
    doc_repo = ExchangeDocumentRepository(db)
    exchange_data = []
    for exch in exchanges:
        latest = await snapshot_repo.get_latest(exch.id)
        docs = await doc_repo.get_by_exchange(exch.id)
        exchange_data.append(
            {
                "exchange": exch,
                "latest_snapshot": latest,
                "version": latest.version if latest else 0,
                "last_updated": latest.created_at if latest else None,
                "status": latest.status.value if latest else "NO_DATA",
                "doc_count": len(docs),
            }
        )

    change_repo = FeeChangeRepository(db)
    recent_changes = await change_repo.get_recent(days=30, limit=10)

    user = await _get_current_user_from_cookie(request, db)

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "exchange_data": exchange_data,
            "recent_changes": recent_changes,
            "cents_to_dollars": _cents_to_dollars,
            "user": user,
            "success": request.query_params.get("success"),
            "error": request.query_params.get("error"),
        },
    )


# ---------------------------------------------------------------------------
# Exchange detail
# ---------------------------------------------------------------------------


@router.get("/dashboard/exchanges/{code}", response_class=HTMLResponse)
async def exchange_detail(
    code: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Detail page for a single exchange showing current fees and version history."""
    exchange_repo = ExchangeRepository(db)
    exchange = await exchange_repo.get_by_code(code.upper())
    if not exchange:
        return templates.TemplateResponse(
            "dashboard.html",
            {
                "request": request,
                "exchange_data": [],
                "recent_changes": [],
                "cents_to_dollars": _cents_to_dollars,
                "user": None,
                "error": f"Exchange '{code}' not found.",
            },
        )

    snapshot_repo = SnapshotRepository(db)
    latest_snapshot = await snapshot_repo.get_latest(exchange.id)

    fee_repo = NormalizedFeeRepository(db)
    fees = await fee_repo.get_latest_for_exchange(exchange.id)

    versions = await snapshot_repo.get_history(exchange.id, limit=20)

    documents = []
    if latest_snapshot:
        doc_repo = ScrapedDocumentRepository(db)
        documents = await doc_repo.get_by_snapshot(latest_snapshot.id)

    user = await _get_current_user_from_cookie(request, db)

    # Pending document count for badge
    ex_doc_repo = ExchangeDocumentRepository(db)
    pending_docs = await ex_doc_repo.get_pending_review(exchange_id=exchange.id)
    pending_doc_count = len(pending_docs)

    # Enum values for filter dropdowns
    participant_types = [pt.value for pt in ParticipantType]
    security_classes = [sc.value for sc in SecurityClass]
    order_types = [ot.value for ot in OrderType]
    fee_types = [ft.value for ft in FeeType]

    return templates.TemplateResponse(
        "exchange.html",
        {
            "request": request,
            "exchange": exchange,
            "latest_snapshot": latest_snapshot,
            "fees": fees,
            "versions": versions,
            "documents": documents,
            "cents_to_dollars": _cents_to_dollars,
            "format_file_size": _format_file_size,
            "user": user,
            "pending_doc_count": pending_doc_count,
            "participant_types": participant_types,
            "security_classes": security_classes,
            "order_types": order_types,
            "fee_types": fee_types,
            "success": request.query_params.get("success"),
            "error": request.query_params.get("error"),
        },
    )


# ---------------------------------------------------------------------------
# Document download
# ---------------------------------------------------------------------------


@router.get("/dashboard/exchanges/{code}/documents/{doc_id}/download")
async def download_document(
    code: str,
    doc_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Download a scraped source document from MinIO storage."""
    import io
    import uuid as _uuid

    from exnot.storage.minio_client import DocumentStorage

    try:
        parsed_id = _uuid.UUID(doc_id)
    except ValueError:
        return HTMLResponse("Invalid document ID", status_code=400)

    doc_repo = ScrapedDocumentRepository(db)
    doc = await doc_repo.get_by_id(parsed_id)
    if not doc:
        return HTMLResponse("Document not found", status_code=404)

    storage = DocumentStorage()
    data = storage.retrieve(doc.storage_path)

    # Derive filename from the storage_path (last segment)
    filename = doc.storage_path.rsplit("/", 1)[-1] if "/" in doc.storage_path else doc.storage_path

    return StreamingResponse(
        io.BytesIO(data),
        media_type=doc.content_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Scrape triggers
# ---------------------------------------------------------------------------


@router.post("/dashboard/exchanges/{code}/scrape")
async def trigger_scrape(
    code: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Trigger a scrape for a single exchange from the dashboard."""
    user = await _get_current_user_from_cookie(request, db)
    if not user or not user.is_admin:
        return RedirectResponse(
            url=f"/dashboard/exchanges/{code}?error=Admin+login+required",
            status_code=303,
        )

    exchange_repo = ExchangeRepository(db)
    exchange = await exchange_repo.get_by_code(code.upper())
    if not exchange:
        return RedirectResponse(
            url=f"/dashboard?error=Exchange+{code}+not+found",
            status_code=303,
        )

    try:
        from exnot.workers.tasks import scrape_and_process_exchange

        scrape_and_process_exchange.delay(code.upper())
        return RedirectResponse(
            url=f"/dashboard/exchanges/{code}?success=Scrape+triggered+for+{code.upper()}",
            status_code=303,
        )
    except Exception as e:
        return RedirectResponse(
            url=f"/dashboard/exchanges/{code}?error=Failed+to+trigger+scrape:+{e}",
            status_code=303,
        )


@router.post("/dashboard/scrape-all")
async def trigger_scrape_all_dashboard(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Trigger a scrape for all active exchanges from the dashboard."""
    user = await _get_current_user_from_cookie(request, db)
    if not user or not user.is_admin:
        return RedirectResponse(
            url="/dashboard?error=Admin+login+required",
            status_code=303,
        )

    try:
        from exnot.workers.tasks import daily_fee_schedule_check

        daily_fee_schedule_check.delay()
        return RedirectResponse(
            url="/dashboard?success=Scrape+triggered+for+all+exchanges",
            status_code=303,
        )
    except Exception as e:
        return RedirectResponse(
            url=f"/dashboard?error=Failed+to+trigger+scrape:+{e}",
            status_code=303,
        )


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------


@router.get("/dashboard/compare", response_class=HTMLResponse)
async def compare_page(
    request: Request,
    selected: list[str] = Query(default=[]),
    participant_type: str | None = Query(default=None),
    security_class: str | None = Query(default=None),
    fee_type: str | None = Query(default=None),
    # V3 filters
    origin_code: str | None = Query(default=None),
    liquidity_role: str | None = Query(default=None),
    exec_venue: str | None = Query(default=None),
    product_type: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Fee comparison page across multiple exchanges."""
    exchange_repo = ExchangeRepository(db)
    all_exchanges = await exchange_repo.get_all(active_only=True)

    comparison_rows: list[dict] = []
    selected_codes: list[str] = [s.upper() for s in selected]

    if selected_codes:
        fee_repo = NormalizedFeeRepository(db)

        # Gather fees per exchange
        exchange_fees: dict[str, list[NormalizedFee]] = {}
        for sel_code in selected_codes:
            exch = await exchange_repo.get_by_code(sel_code)
            if not exch:
                continue
            fees = await fee_repo.get_latest_for_exchange(exch.id)
            exchange_fees[sel_code] = fees

        # Build comparison rows keyed by (participant_type, security_class, order_type, fee_type)
        all_keys: set[tuple] = set()
        for code_key, fees in exchange_fees.items():
            for f in fees:
                # Apply filters
                if participant_type and f.participant_type.value != participant_type.upper():
                    continue
                if security_class and f.security_class.value != security_class.upper():
                    continue
                if fee_type and f.fee_type.value != fee_type.upper():
                    continue
                # V3 filters
                if origin_code and (not f.origin_code or f.origin_code.upper() != origin_code.upper()):
                    continue
                if liquidity_role and (not f.liquidity_role or f.liquidity_role.upper() != liquidity_role.upper()):
                    continue
                if exec_venue and (not f.exec_venue or f.exec_venue.upper() != exec_venue.upper()):
                    continue
                if product_type and (not f.product_type or f.product_type.upper() != product_type.upper()):
                    continue
                key = (
                    f.participant_type.value,
                    f.security_class.value,
                    f.order_type.value,
                    f.fee_type.value,
                )
                all_keys.add(key)

        for key in sorted(all_keys):
            row = {
                "participant_type": key[0],
                "security_class": key[1],
                "order_type": key[2],
                "fee_type": key[3],
                "cells": {},
                "cheapest": None,
                "most_expensive": None,
            }
            amounts: dict[str, int] = {}
            for code_key, fees in exchange_fees.items():
                for f in fees:
                    fkey = (
                        f.participant_type.value,
                        f.security_class.value,
                        f.order_type.value,
                        f.fee_type.value,
                    )
                    if fkey == key:
                        row["cells"][code_key] = {
                            "amount_cents": f.amount_cents,
                            "amount": _cents_to_dollars(f.amount_cents),
                            "is_rebate": f.is_rebate,
                            "canonical_fee": f.canonical_fee.display_name if f.canonical_fee else None,
                            "canonical_fee_id": f.canonical_fee_id,
                        }
                        amounts[code_key] = f.amount_cents
                        break

            if amounts:
                row["cheapest"] = min(amounts, key=amounts.get)  # type: ignore[arg-type]
                row["most_expensive"] = max(amounts, key=amounts.get)  # type: ignore[arg-type]

            comparison_rows.append(row)

    user = await _get_current_user_from_cookie(request, db)

    # Enum values for filter dropdowns
    participant_types = [pt.value for pt in ParticipantType]
    security_classes = [sc.value for sc in SecurityClass]
    fee_types = [ft.value for ft in FeeType]

    # V3 enum values for advanced filters
    from exnot.normalizer.schema import ExecVenue, LiquidityRole, OriginCode, ProductType

    origin_codes = [oc.value for oc in OriginCode]
    liquidity_roles = [lr.value for lr in LiquidityRole]
    exec_venues = [ev.value for ev in ExecVenue]
    product_types_v3 = [pt.value for pt in ProductType]

    return templates.TemplateResponse(
        "comparison.html",
        {
            "request": request,
            "all_exchanges": all_exchanges,
            "selected_codes": selected_codes,
            "comparison_rows": comparison_rows,
            "participant_types": participant_types,
            "security_classes": security_classes,
            "fee_types": fee_types,
            "current_participant_type": participant_type or "",
            "current_security_class": security_class or "",
            "current_fee_type": fee_type or "",
            "origin_codes": origin_codes,
            "liquidity_roles": liquidity_roles,
            "exec_venues": exec_venues,
            "product_types_v3": product_types_v3,
            "current_origin_code": origin_code or "",
            "current_liquidity_role": liquidity_role or "",
            "current_exec_venue": exec_venue or "",
            "current_product_type": product_type or "",
            "user": user,
        },
    )


# ---------------------------------------------------------------------------
# Changes history
# ---------------------------------------------------------------------------


@router.get("/dashboard/changes", response_class=HTMLResponse)
async def changes_page(
    request: Request,
    days: int = Query(default=30, ge=1, le=365),
    exchange_code: str | None = Query(default=None),
    change_type: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Change history page with filters."""
    change_repo = FeeChangeRepository(db)
    changes = await change_repo.get_recent(days=days, limit=200)

    # Apply optional filters
    if exchange_code:
        changes = [c for c in changes if c.exchange and c.exchange.code == exchange_code.upper()]
    if change_type:
        changes = [c for c in changes if c.change_type.value == change_type.upper()]

    exchange_repo = ExchangeRepository(db)
    all_exchanges = await exchange_repo.get_all(active_only=False)

    user = await _get_current_user_from_cookie(request, db)

    change_types = [ct.value for ct in ChangeType]

    return templates.TemplateResponse(
        "changes.html",
        {
            "request": request,
            "changes": changes,
            "all_exchanges": all_exchanges,
            "change_types": change_types,
            "current_days": days,
            "current_exchange_code": exchange_code or "",
            "current_change_type": change_type or "",
            "cents_to_dollars": _cents_to_dollars,
            "user": user,
        },
    )


# ---------------------------------------------------------------------------
# Subscribe
# ---------------------------------------------------------------------------


@router.get("/dashboard/subscribe", response_class=HTMLResponse)
async def subscribe_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Subscription management page."""
    exchange_repo = ExchangeRepository(db)
    all_exchanges = await exchange_repo.get_all(active_only=True)

    user = await _get_current_user_from_cookie(request, db)

    frequencies = [nf.value for nf in NotificationFrequency]

    return templates.TemplateResponse(
        "subscribe.html",
        {
            "request": request,
            "all_exchanges": all_exchanges,
            "frequencies": frequencies,
            "user": user,
            "success": request.query_params.get("success"),
            "error": request.query_params.get("error"),
        },
    )


@router.post("/dashboard/subscribe", response_class=HTMLResponse)
async def subscribe_submit(
    request: Request,
    db: AsyncSession = Depends(get_db),
    email: str = Form(...),
    name: str = Form(""),
    frequency: str = Form("DAILY_DIGEST"),
):
    """Handle subscription form submission."""
    form_data = await request.form()
    exchange_codes = form_data.getlist("exchanges")

    subscriber_repo = SubscriberRepository(db)
    existing = await subscriber_repo.get_by_email(email)
    if existing:
        return RedirectResponse(
            url="/dashboard/subscribe?error=Email+already+subscribed",
            status_code=303,
        )

    subscriber = Subscriber(
        email=email,
        name=name if name else None,
        exchanges_filter=list(exchange_codes) if exchange_codes else None,
        notification_frequency=NotificationFrequency(frequency),
    )
    await subscriber_repo.create(subscriber)
    await db.commit()

    return RedirectResponse(
        url="/dashboard/subscribe?success=1",
        status_code=303,
    )


# ---------------------------------------------------------------------------
# Unsubscribe
# ---------------------------------------------------------------------------


@router.get("/dashboard/unsubscribe", response_class=HTMLResponse)
async def unsubscribe_page(
    request: Request,
    email: str = Query(default=""),
    token: str = Query(default=""),
    db: AsyncSession = Depends(get_db),
):
    """Unsubscribe page -- deactivates the subscriber by email."""
    message = None
    error = None

    if email:
        subscriber_repo = SubscriberRepository(db)
        subscriber = await subscriber_repo.get_by_email(email)
        if subscriber and subscriber.is_active:
            subscriber.is_active = False
            await db.commit()
            message = "You have been successfully unsubscribed."
        elif subscriber and not subscriber.is_active:
            message = "This email is already unsubscribed."
        else:
            error = "Email address not found in our subscriber list."

    user = await _get_current_user_from_cookie(request, db)

    return templates.TemplateResponse(
        "unsubscribe.html",
        {
            "request": request,
            "email": email,
            "message": message,
            "error": error,
            "user": user,
        },
    )


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------


@router.get("/dashboard/login", response_class=HTMLResponse)
async def login_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Login page."""
    user = await _get_current_user_from_cookie(request, db)
    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "user": user,
            "error": request.query_params.get("error"),
        },
    )


@router.post("/dashboard/login", response_class=HTMLResponse)
async def login_submit(
    request: Request,
    db: AsyncSession = Depends(get_db),
    username: str = Form(...),
    password: str = Form(...),
):
    """Handle login form submission -- set cookie with JWT."""
    from exnot.api.deps import create_access_token, verify_password

    user_repo = UserRepository(db)
    user = await user_repo.get_by_username(username)

    if not user or not verify_password(password, user.hashed_password):
        return RedirectResponse(
            url="/dashboard/login?error=Invalid+username+or+password",
            status_code=303,
        )

    if not user.is_active:
        return RedirectResponse(
            url="/dashboard/login?error=Account+is+disabled",
            status_code=303,
        )

    token = create_access_token({"sub": user.email})
    response = RedirectResponse(url="/dashboard", status_code=303)
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        max_age=60 * 60 * 24,  # 24 hours
        samesite="lax",
    )
    return response


@router.get("/dashboard/logout")
async def logout(request: Request):
    """Clear the session cookie and redirect to dashboard."""
    response = RedirectResponse(url="/dashboard", status_code=303)
    response.delete_cookie("access_token")
    return response


# ---------------------------------------------------------------------------
# Pipeline Monitor
# ---------------------------------------------------------------------------


@router.get("/dashboard/monitor", response_class=HTMLResponse)
async def monitor_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Pipeline monitor showing recent scrape log entries."""
    user = await _get_current_user_from_cookie(request, db)
    if not user or not user.is_admin:
        return RedirectResponse(
            url="/dashboard/login?error=Admin+login+required",
            status_code=303,
        )

    scrape_log_repo = ScrapeLogRepository(db)
    logs = await scrape_log_repo.get_all_recent(limit=100)

    return templates.TemplateResponse(
        "monitor.html",
        {
            "request": request,
            "logs": logs,
            "user": user,
        },
    )


@router.get("/dashboard/monitor/logs/{log_id}", response_class=HTMLResponse)
async def get_pipeline_logs(
    log_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Fetch stored pipeline events for a completed run."""
    user = await _get_current_user_from_cookie(request, db)
    if not user or not user.is_admin:
        return HTMLResponse('<p class="text-red-600 text-xs">Unauthorized</p>', status_code=403)

    from exnot.agents.streaming import get_stored_events

    events = get_stored_events(log_id)

    if not events:
        return HTMLResponse('<p class="text-slate-400 dark:text-slate-500 italic text-xs">No stored events for this run (events expire after 24 hours).</p>')

    import html

    lines = []
    for event in events:
        etype = event.get("type", "unknown")
        if etype == "assistant":
            for block in event.get("blocks", []):
                btype = block.get("type", "")
                if btype == "tool_call":
                    name = html.escape(block.get("name", ""))
                    model = html.escape(event.get("model", "") or "")
                    sub = " (subagent)" if event.get("is_subagent") else ""
                    model_span = f' <span class="text-slate-400">[{model}]</span>' if model else ""
                    lines.append(f'<div class="py-0.5 border-b border-slate-100 dark:border-slate-800">'
                                 f'<span class="text-purple-600 dark:text-purple-400 font-semibold">TOOL</span> '
                                 f'{name}{sub}{model_span}'
                                 f'</div>')
                    inp = html.escape(block.get("input", ""))
                    if inp:
                        lines.append(f'<details class="ml-4 mb-1"><summary class="cursor-pointer text-slate-500 dark:text-slate-400 text-xs">Input</summary>'
                                     f'<pre class="mt-1 p-2 bg-slate-100 dark:bg-slate-800 rounded text-xs overflow-x-auto max-h-48 overflow-y-auto">{inp}</pre></details>')
                elif btype == "text":
                    text = html.escape(block.get("text", "")[:500])
                    lines.append(f'<div class="py-0.5 border-b border-slate-100 dark:border-slate-800">'
                                 f'<span class="text-blue-600 dark:text-blue-400 font-semibold">TEXT</span> {text}</div>')
                elif btype == "reasoning":
                    text = html.escape(block.get("text", "")[:300])
                    lines.append(f'<div class="py-0.5 border-b border-slate-100 dark:border-slate-800">'
                                 f'<span class="text-amber-600 dark:text-amber-400 font-semibold">THINK</span> '
                                 f'<span class="text-slate-500 dark:text-slate-400">{text}</span></div>')
        elif etype == "result":
            is_error = event.get("is_error", False)
            badge = '<span class="text-red-600 dark:text-red-400 font-bold">RESULT (ERROR)</span>' if is_error else '<span class="text-green-600 dark:text-green-400 font-bold">RESULT</span>'
            cost = float(event.get("total_cost_usd", 0) or 0)
            lines.append(f'<div class="py-0.5 border-b border-slate-100 dark:border-slate-800">'
                         f'{badge} stop={html.escape(str(event.get("stop_reason", "?")))} '
                         f'cost=${cost:.4f} turns={event.get("num_turns", 0)}</div>')
            result_text = event.get("result")
            if result_text:
                lines.append(f'<details class="ml-4 mb-1"><summary class="cursor-pointer text-slate-500 dark:text-slate-400 text-xs">Result output</summary>'
                             f'<pre class="mt-1 p-2 bg-slate-100 dark:bg-slate-800 rounded text-xs overflow-x-auto max-h-48 overflow-y-auto">{html.escape(result_text)}</pre></details>')
        elif etype == "log":
            level = event.get("level", "info")
            color_map = {"info": "text-blue-600 dark:text-blue-400", "error": "text-red-600 dark:text-red-400", "warn": "text-amber-600 dark:text-amber-400"}
            color = color_map.get(level, "text-slate-600 dark:text-slate-400")
            lines.append(f'<div class="py-0.5 border-b border-slate-100 dark:border-slate-800">'
                         f'<span class="{color} font-semibold">{html.escape(level.upper())}</span> '
                         f'{html.escape(event.get("message", ""))}</div>')
        elif etype == "system":
            lines.append(f'<div class="py-0.5 border-b border-slate-100 dark:border-slate-800">'
                         f'<span class="text-slate-500 dark:text-slate-400 font-semibold">SYS</span> '
                         f'{html.escape(event.get("raw", "")[:300])}</div>')

    return HTMLResponse(
        f'<div class="text-xs text-slate-500 dark:text-slate-400 mb-2">{len(events)} events stored</div>'
        + "\n".join(lines)
    )


@router.post("/dashboard/monitor/kill/{log_id}", response_class=HTMLResponse)
async def kill_pipeline(
    log_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Kill a running pipeline by revoking its Celery task."""
    user = await _get_current_user_from_cookie(request, db)
    if not user or not user.is_admin:
        return HTMLResponse('<span class="text-red-600 text-xs">Unauthorized</span>', status_code=403)

    from exnot.db.models import ScrapeLog, ScrapeStatus

    result = await db.execute(select(ScrapeLog).where(ScrapeLog.id == log_id))
    log_entry = result.scalar_one_or_none()

    if not log_entry:
        return HTMLResponse('<span class="text-red-600 text-xs">Not found</span>', status_code=404)

    if log_entry.status != ScrapeStatus.RUNNING:
        return HTMLResponse('<span class="text-slate-500 text-xs">Not running</span>')

    # Revoke the Celery task
    killed = False
    if log_entry.celery_task_id:
        try:
            from exnot.workers.celery_app import celery_app

            celery_app.control.revoke(log_entry.celery_task_id, terminate=True, signal="SIGTERM")
            killed = True
        except Exception:
            pass

    # Update the scrape log
    from datetime import datetime

    log_entry.status = ScrapeStatus.FAILED
    log_entry.completed_at = datetime.utcnow()
    log_entry.error_message = "Manually killed by admin" + ("" if killed else " (no task ID, marked only)")
    await db.commit()

    return HTMLResponse(
        '<span class="inline-flex items-center rounded-full bg-red-100 dark:bg-red-900/50 px-2 py-0.5 text-xs font-medium text-red-800 dark:text-red-300">'
        '<span class="mr-1 h-1.5 w-1.5 rounded-full bg-red-500 inline-block"></span>'
        'KILLED</span>'
    )


# ---------------------------------------------------------------------------
# Admin panel
# ---------------------------------------------------------------------------


@router.get("/dashboard/admin", response_class=HTMLResponse)
async def admin_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Admin panel for scrape management and logs."""
    user = await _get_current_user_from_cookie(request, db)
    if not user or not user.is_admin:
        return RedirectResponse(
            url="/dashboard/login?error=Admin+login+required",
            status_code=303,
        )

    exchange_repo = ExchangeRepository(db)
    exchanges = await exchange_repo.get_all(active_only=True)

    scrape_log_repo = ScrapeLogRepository(db)
    scrape_logs = await scrape_log_repo.get_all_recent(limit=50)

    return templates.TemplateResponse(
        "admin.html",
        {
            "request": request,
            "exchanges": exchanges,
            "scrape_logs": scrape_logs,
            "user": user,
            "message": request.query_params.get("message"),
        },
    )


@router.post("/dashboard/admin/scrape-all")
async def admin_scrape_all(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Trigger a scrape for all active exchanges from the admin panel."""
    user = await _get_current_user_from_cookie(request, db)
    if not user or not user.is_admin:
        return RedirectResponse(
            url="/dashboard/login?error=Admin+login+required",
            status_code=303,
        )

    try:
        from exnot.workers.tasks import daily_fee_schedule_check

        daily_fee_schedule_check.delay()
        return RedirectResponse(
            url="/dashboard/admin?message=Scrape+triggered+for+all+exchanges",
            status_code=303,
        )
    except Exception as e:
        return RedirectResponse(
            url=f"/dashboard/admin?message=Failed+to+trigger+scrape:+{e}",
            status_code=303,
        )


@router.post("/dashboard/admin/scrape/{code}")
async def admin_scrape_exchange(
    code: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Trigger a scrape for a single exchange from the admin panel."""
    user = await _get_current_user_from_cookie(request, db)
    if not user or not user.is_admin:
        return RedirectResponse(
            url="/dashboard/login?error=Admin+login+required",
            status_code=303,
        )

    exchange_repo = ExchangeRepository(db)
    exchange = await exchange_repo.get_by_code(code.upper())
    if not exchange:
        return RedirectResponse(
            url=f"/dashboard/admin?message=Exchange+{code}+not+found",
            status_code=303,
        )

    try:
        from exnot.workers.tasks import scrape_and_process_exchange

        scrape_and_process_exchange.delay(code.upper())
        return RedirectResponse(
            url=f"/dashboard/admin?message=Scrape+triggered+for+{code.upper()}",
            status_code=303,
        )
    except Exception as e:
        return RedirectResponse(
            url=f"/dashboard/admin?message=Failed+to+trigger+scrape:+{e}",
            status_code=303,
        )


# ---------------------------------------------------------------------------
# Claude Agent SDK Auth
# ---------------------------------------------------------------------------


def _get_claude_auth_status() -> dict:
    """Check Claude Agent SDK auth status."""
    import shutil
    import subprocess
    from pathlib import Path

    credentials_path = Path.home() / ".claude" / ".credentials.json"
    status = {
        "credentials_exist": credentials_path.exists(),
        "credentials_path": str(credentials_path),
        "auth_type": "Unknown",
        "last_modified": None,
        "file_size": 0,
        "node_available": False,
        "node_version": None,
        "sdk_version": None,
    }

    if credentials_path.exists():
        import json
        from datetime import datetime

        stat = credentials_path.stat()
        status["file_size"] = stat.st_size
        status["last_modified"] = datetime.fromtimestamp(stat.st_mtime).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        try:
            data = json.loads(credentials_path.read_text())
            if "claudeAiOauth" in data:
                status["auth_type"] = "OAuth (Claude subscription)"
            elif "apiKey" in data:
                status["auth_type"] = "API Key"
            else:
                status["auth_type"] = "Unknown format"
        except Exception:
            status["auth_type"] = "Invalid JSON"

    # Check Node.js
    if shutil.which("node"):
        try:
            result = subprocess.run(
                ["node", "--version"], capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                status["node_available"] = True
                status["node_version"] = result.stdout.strip()
        except Exception:
            pass

    # Check SDK
    try:
        import claude_agent_sdk

        status["sdk_version"] = getattr(claude_agent_sdk, "__version__", "installed")
    except ImportError:
        pass

    return status


@router.get("/dashboard/admin/claude-auth", response_class=HTMLResponse)
async def claude_auth_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Claude Agent SDK authentication management page."""
    user = await _get_current_user_from_cookie(request, db)
    if not user or not user.is_admin:
        return RedirectResponse(
            url="/dashboard/login?error=Admin+login+required",
            status_code=303,
        )

    auth_status = _get_claude_auth_status()
    return templates.TemplateResponse(
        "claude_auth.html",
        {
            "request": request,
            "auth_status": auth_status,
            "user": user,
            "message": request.query_params.get("message"),
            "error": request.query_params.get("error"),
        },
    )


@router.post("/dashboard/admin/claude-auth/upload")
async def claude_auth_upload(
    request: Request,
    credentials_json: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """Upload Claude credentials JSON."""
    import json
    from pathlib import Path

    user = await _get_current_user_from_cookie(request, db)
    if not user or not user.is_admin:
        return RedirectResponse(
            url="/dashboard/login?error=Admin+login+required",
            status_code=303,
        )

    # Validate JSON
    try:
        data = json.loads(credentials_json.strip())
    except json.JSONDecodeError as e:
        return RedirectResponse(
            url=f"/dashboard/admin/claude-auth?error=Invalid+JSON:+{e}",
            status_code=303,
        )

    # Basic validation
    if not isinstance(data, dict):
        return RedirectResponse(
            url="/dashboard/admin/claude-auth?error=Credentials+must+be+a+JSON+object",
            status_code=303,
        )

    if "claudeAiOauth" not in data and "apiKey" not in data:
        return RedirectResponse(
            url="/dashboard/admin/claude-auth?error=Missing+claudeAiOauth+or+apiKey+field",
            status_code=303,
        )

    # Write credentials
    credentials_path = Path.home() / ".claude" / ".credentials.json"
    try:
        credentials_path.parent.mkdir(parents=True, exist_ok=True)
        credentials_path.write_text(json.dumps(data, indent=2))
        credentials_path.chmod(0o600)
    except Exception as e:
        return RedirectResponse(
            url=f"/dashboard/admin/claude-auth?error=Failed+to+write+credentials:+{e}",
            status_code=303,
        )

    return RedirectResponse(
        url="/dashboard/admin/claude-auth?message=Credentials+uploaded+successfully",
        status_code=303,
    )


# ---------------------------------------------------------------------------
# Claude Agent SDK Test
# ---------------------------------------------------------------------------


def _get_sdk_info() -> dict:
    """Gather basic SDK info for the test page."""
    info = {"sdk_version": None, "cli_path": None, "has_auth": False}
    try:
        import claude_agent_sdk

        info["sdk_version"] = getattr(claude_agent_sdk, "__version__", "installed")
        # Find bundled CLI path
        from pathlib import Path

        bundled = Path(claude_agent_sdk.__file__).parent / "_bundled" / "claude"
        info["cli_path"] = str(bundled) if bundled.exists() else "bundled CLI not found"
    except ImportError:
        pass

    # Check auth
    from pathlib import Path

    claude_json = Path.home() / ".claude.json"
    credentials = Path.home() / ".claude" / ".credentials.json"
    info["has_auth"] = claude_json.exists() or credentials.exists()
    return info


@router.get("/dashboard/admin/sdk-test", response_class=HTMLResponse)
async def sdk_test_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Claude Agent SDK test page."""
    user = await _get_current_user_from_cookie(request, db)
    if not user or not user.is_admin:
        return RedirectResponse(
            url="/dashboard/login?error=Admin+login+required",
            status_code=303,
        )

    sdk_info = _get_sdk_info()
    return templates.TemplateResponse(
        "sdk_test.html",
        {
            "request": request,
            "user": user,
            "sdk_info": sdk_info,
        },
    )


@router.post("/dashboard/admin/sdk-test/run", response_class=HTMLResponse)
async def sdk_test_run(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Run a simple SDK test and return the result as HTML fragment."""
    user = await _get_current_user_from_cookie(request, db)
    if not user or not user.is_admin:
        return HTMLResponse('<p class="text-red-600">Admin login required.</p>', status_code=403)

    import asyncio
    import html
    import os
    import time

    lines: list[str] = []
    start = time.time()

    try:
        # Prevent nested session error
        os.environ.pop("CLAUDECODE", None)

        from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

        options = ClaudeAgentOptions(model="haiku")

        result_text = ""
        cost = None
        turns = None

        async for message in query(prompt="Say hello in one sentence.", options=options):
            msg_type = type(message).__name__
            if isinstance(message, ResultMessage):
                result_text = message.result or ""
                cost = message.total_cost_usd
                turns = message.num_turns
                lines.append(f"[ResultMessage] stop_reason={message.stop_reason}")
            else:
                lines.append(f"[{msg_type}] received")

        elapsed = time.time() - start

        output = f'<div class="space-y-3">\n'
        output += f'  <div class="flex items-center gap-2">\n'
        output += f'    <span class="inline-flex items-center rounded-full bg-green-100 px-2.5 py-0.5 text-xs font-medium text-green-800">SUCCESS</span>\n'
        output += f'    <span class="text-slate-500 text-xs">{elapsed:.2f}s</span>\n'
        output += f'  </div>\n'
        output += f'  <div class="bg-white border border-slate-200 rounded p-3">\n'
        output += f'    <p class="text-slate-800 font-medium">Response:</p>\n'
        output += f'    <p class="text-slate-700 mt-1">{html.escape(result_text)}</p>\n'
        output += f'  </div>\n'
        output += f'  <dl class="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">\n'
        output += f'    <div><dt class="text-slate-500">Cost</dt><dd class="font-mono">${cost:.6f}</dd></div>\n' if cost is not None else ''
        output += f'    <div><dt class="text-slate-500">Turns</dt><dd class="font-mono">{turns}</dd></div>\n' if turns is not None else ''
        output += f'    <div><dt class="text-slate-500">Duration</dt><dd class="font-mono">{elapsed:.2f}s</dd></div>\n'
        output += f'    <div><dt class="text-slate-500">Messages</dt><dd class="font-mono">{len(lines)}</dd></div>\n'
        output += f'  </dl>\n'
        output += f'  <details class="text-xs">\n'
        output += f'    <summary class="cursor-pointer text-slate-500 hover:text-slate-700">Raw messages</summary>\n'
        output += f'    <pre class="mt-2 bg-slate-100 p-2 rounded overflow-x-auto">{html.escape(chr(10).join(lines))}</pre>\n'
        output += f'  </details>\n'
        output += f'</div>'

        return HTMLResponse(output)

    except Exception as e:
        elapsed = time.time() - start
        import html as html_mod
        import traceback

        tb = traceback.format_exc()
        output = f'<div class="space-y-3">\n'
        output += f'  <div class="flex items-center gap-2">\n'
        output += f'    <span class="inline-flex items-center rounded-full bg-red-100 px-2.5 py-0.5 text-xs font-medium text-red-800">FAILED</span>\n'
        output += f'    <span class="text-slate-500 text-xs">{elapsed:.2f}s</span>\n'
        output += f'  </div>\n'
        output += f'  <div class="bg-red-50 border border-red-200 rounded p-3">\n'
        output += f'    <p class="text-red-800 font-medium">{html_mod.escape(type(e).__name__)}: {html_mod.escape(str(e))}</p>\n'
        output += f'  </div>\n'
        output += f'  <details class="text-xs">\n'
        output += f'    <summary class="cursor-pointer text-slate-500 hover:text-slate-700">Full traceback</summary>\n'
        output += f'    <pre class="mt-2 bg-red-50 p-2 rounded overflow-x-auto text-red-700">{html_mod.escape(tb)}</pre>\n'
        output += f'  </details>\n'
        output += f'</div>'

        return HTMLResponse(output)


# ---------------------------------------------------------------------------
# Exchange documents review
# ---------------------------------------------------------------------------


@router.get("/dashboard/exchanges/{code}/documents", response_class=HTMLResponse)
async def exchange_documents(
    request: Request,
    code: str,
    db: AsyncSession = Depends(get_db),
):
    """Document review page for an exchange showing all discovered documents."""
    user = await _get_current_user_from_cookie(request, db)
    exchange_repo = ExchangeRepository(db)
    doc_repo = ExchangeDocumentRepository(db)

    exchange = await exchange_repo.get_by_code(code.upper())
    if not exchange:
        return RedirectResponse("/dashboard", status_code=302)

    documents = await doc_repo.get_by_exchange(exchange.id)

    return templates.TemplateResponse(
        "documents.html",
        {
            "request": request,
            "exchange": exchange,
            "documents": documents,
            "user": user,
            "success": request.query_params.get("success"),
            "error": request.query_params.get("error"),
        },
    )


@router.post("/dashboard/exchanges/{code}/documents/{doc_id}/approve")
async def approve_document(
    code: str,
    doc_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Approve a discovered document (admin-only)."""
    import uuid as _uuid

    user = await _get_current_user_from_cookie(request, db)
    if not user or not user.is_admin:
        return RedirectResponse(
            url=f"/dashboard/exchanges/{code}/documents?error=Admin+login+required",
            status_code=303,
        )

    try:
        parsed_id = _uuid.UUID(doc_id)
    except ValueError:
        return RedirectResponse(
            url=f"/dashboard/exchanges/{code}/documents?error=Invalid+document+ID",
            status_code=303,
        )

    doc_repo = ExchangeDocumentRepository(db)
    await doc_repo.update_status(parsed_id, DocumentStatus.APPROVED, approved_by=user.id)
    await db.commit()

    return RedirectResponse(
        url=f"/dashboard/exchanges/{code}/documents?success=Document+approved",
        status_code=303,
    )


@router.post("/dashboard/exchanges/{code}/documents/{doc_id}/approve-pin")
async def approve_and_pin_document(
    code: str,
    doc_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Approve and pin a document, deriving a URL pattern (admin-only)."""
    import uuid as _uuid

    from exnot.discovery.url_patterns import derive_url_pattern

    user = await _get_current_user_from_cookie(request, db)
    if not user or not user.is_admin:
        return RedirectResponse(
            url=f"/dashboard/exchanges/{code}/documents?error=Admin+login+required",
            status_code=303,
        )

    try:
        parsed_id = _uuid.UUID(doc_id)
    except ValueError:
        return RedirectResponse(
            url=f"/dashboard/exchanges/{code}/documents?error=Invalid+document+ID",
            status_code=303,
        )

    doc_repo = ExchangeDocumentRepository(db)
    doc = await doc_repo.update_status(parsed_id, DocumentStatus.APPROVED, approved_by=user.id)
    if doc:
        doc.is_pinned = True
        doc.url_pattern = derive_url_pattern(doc.source_url)
        await db.commit()

    return RedirectResponse(
        url=f"/dashboard/exchanges/{code}/documents?success=Document+approved+and+pinned",
        status_code=303,
    )


@router.post("/dashboard/exchanges/{code}/documents/{doc_id}/reject")
async def reject_document(
    code: str,
    doc_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Reject a discovered document (admin-only)."""
    import uuid as _uuid

    user = await _get_current_user_from_cookie(request, db)
    if not user or not user.is_admin:
        return RedirectResponse(
            url=f"/dashboard/exchanges/{code}/documents?error=Admin+login+required",
            status_code=303,
        )

    try:
        parsed_id = _uuid.UUID(doc_id)
    except ValueError:
        return RedirectResponse(
            url=f"/dashboard/exchanges/{code}/documents?error=Invalid+document+ID",
            status_code=303,
        )

    doc_repo = ExchangeDocumentRepository(db)
    await doc_repo.update_status(parsed_id, DocumentStatus.REJECTED, approved_by=user.id)
    await db.commit()

    return RedirectResponse(
        url=f"/dashboard/exchanges/{code}/documents?success=Document+rejected",
        status_code=303,
    )


@router.post("/dashboard/exchanges/{code}/documents/{doc_id}/pin")
async def pin_document(
    code: str,
    doc_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Pin a document so it persists across discovery runs (admin-only)."""
    import uuid as _uuid

    user = await _get_current_user_from_cookie(request, db)
    if not user or not user.is_admin:
        return RedirectResponse(
            url=f"/dashboard/exchanges/{code}/documents?error=Admin+login+required",
            status_code=303,
        )

    try:
        parsed_id = _uuid.UUID(doc_id)
    except ValueError:
        return RedirectResponse(
            url=f"/dashboard/exchanges/{code}/documents?error=Invalid+document+ID",
            status_code=303,
        )

    doc_repo = ExchangeDocumentRepository(db)
    doc = await doc_repo.get_by_id(parsed_id)
    if doc:
        doc.is_pinned = True
        await db.commit()

    return RedirectResponse(
        url=f"/dashboard/exchanges/{code}/documents?success=Document+pinned",
        status_code=303,
    )


@router.post("/dashboard/exchanges/{code}/documents/{doc_id}/unpin")
async def unpin_document(
    code: str,
    doc_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Unpin a document (admin-only)."""
    import uuid as _uuid

    user = await _get_current_user_from_cookie(request, db)
    if not user or not user.is_admin:
        return RedirectResponse(
            url=f"/dashboard/exchanges/{code}/documents?error=Admin+login+required",
            status_code=303,
        )

    try:
        parsed_id = _uuid.UUID(doc_id)
    except ValueError:
        return RedirectResponse(
            url=f"/dashboard/exchanges/{code}/documents?error=Invalid+document+ID",
            status_code=303,
        )

    doc_repo = ExchangeDocumentRepository(db)
    doc = await doc_repo.get_by_id(parsed_id)
    if doc:
        doc.is_pinned = False
        await db.commit()

    return RedirectResponse(
        url=f"/dashboard/exchanges/{code}/documents?success=Document+unpinned",
        status_code=303,
    )
