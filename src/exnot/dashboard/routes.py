"""Dashboard web routes using FastAPI + Jinja2 + HTMX."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession

from exnot.config import get_settings
from exnot.db.engine import AsyncSessionLocal, get_db
from exnot.db.models import (
    AgentRunStatus,
    ChangeType,
    DocumentStatus,
    ExchangeDocument,
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
    AgentEventRepository,
    AgentRunRepository,
    ExchangeDocumentRepository,
    ExchangeRepository,
    FeeChangeRepository,
    NormalizedFeeRepository,
    ScrapedDocumentRepository,
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
    exchange_data = []
    for exch in exchanges:
        latest = await snapshot_repo.get_latest(exch.id)
        exchange_data.append(
            {
                "exchange": exch,
                "latest_snapshot": latest,
                "version": latest.version if latest else 0,
                "last_updated": latest.created_at if latest else None,
                "status": latest.status.value if latest else "NO_DATA",
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
# Monitor — real-time agent run monitoring
# ---------------------------------------------------------------------------


@router.get("/dashboard/monitor", response_class=HTMLResponse)
async def monitor_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Main monitor page showing recent agent runs (admin-only)."""
    user = await _get_current_user_from_cookie(request, db)
    if not user or not user.is_admin:
        return RedirectResponse(
            url="/dashboard/login?error=Admin+login+required",
            status_code=303,
        )

    run_repo = AgentRunRepository(db)
    runs = await run_repo.get_recent(limit=50)

    return templates.TemplateResponse(
        "monitor.html",
        {
            "request": request,
            "runs": runs,
            "user": user,
            "success": request.query_params.get("success"),
            "error": request.query_params.get("error"),
        },
    )


@router.get("/dashboard/monitor/stream")
async def monitor_stream(
    request: Request,
    run_id: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    """SSE endpoint for real-time agent run events."""
    user = await _get_current_user_from_cookie(request, db)
    if not user or not user.is_admin:
        return HTMLResponse("Unauthorized", status_code=401)

    from exnot.ai.event_emitter import CHANNEL_ALL, EventEmitter, _channel_for_run

    async def event_generator():
        r = EventEmitter.get_redis_client()
        pubsub = r.pubsub()

        try:
            if run_id:
                import uuid as _uuid

                parsed_run_id = _uuid.UUID(run_id)

                # Replay existing events from DB first
                async with AsyncSessionLocal() as replay_db:
                    event_repo = AgentEventRepository(replay_db)
                    existing_events = await event_repo.get_for_run(parsed_run_id)
                    for ev in existing_events:
                        msg = {
                            "run_id": str(parsed_run_id),
                            "seq": ev.seq,
                            "event_type": ev.event_type.value,
                            "step_name": ev.step_name,
                            "model": ev.model,
                            "input_tokens": ev.input_tokens,
                            "output_tokens": ev.output_tokens,
                            "cost_usd": round(ev.cost_usd, 6) if ev.cost_usd else None,
                            "latency_ms": ev.latency_ms,
                            "created_at": ev.created_at.isoformat() if ev.created_at else None,
                        }
                        yield f"data: {json.dumps(msg)}\n\n"

                # Subscribe to run-specific channel
                pubsub.subscribe(_channel_for_run(parsed_run_id))
            else:
                # Subscribe to global channel
                pubsub.subscribe(CHANNEL_ALL)

            while True:
                if await request.is_disconnected():
                    break
                message = pubsub.get_message(ignore_subscribe_messages=True, timeout=0.1)
                if message and message["type"] == "message":
                    data = message["data"]
                    if isinstance(data, bytes):
                        data = data.decode("utf-8")
                    yield f"data: {data}\n\n"
                else:
                    yield ": keepalive\n\n"
                await asyncio.sleep(0.5)
        finally:
            pubsub.unsubscribe()
            pubsub.close()
            r.close()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/dashboard/monitor/events/{run_id}", response_class=HTMLResponse)
async def monitor_events(
    run_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """HTML fragment with events for a specific run."""
    user = await _get_current_user_from_cookie(request, db)
    if not user or not user.is_admin:
        return HTMLResponse("Unauthorized", status_code=401)

    import uuid as _uuid

    try:
        parsed_id = _uuid.UUID(run_id)
    except ValueError:
        return HTMLResponse("Invalid run ID", status_code=400)

    run_repo = AgentRunRepository(db)
    run = await run_repo.get_by_id(parsed_id)
    if not run:
        return HTMLResponse("Run not found", status_code=404)

    event_repo = AgentEventRepository(db)
    events = await event_repo.get_for_run(parsed_id)

    return templates.TemplateResponse(
        "monitor_events.html",
        {
            "request": request,
            "run": run,
            "events": events,
        },
    )


@router.post("/dashboard/monitor/{run_id}/stop")
async def monitor_stop_run(
    run_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Stop a single running agent run (admin-only)."""
    user = await _get_current_user_from_cookie(request, db)
    if not user or not user.is_admin:
        return RedirectResponse(
            url="/dashboard/login?error=Admin+login+required",
            status_code=303,
        )

    import uuid as _uuid

    from exnot.ai.event_emitter import EventEmitter
    from exnot.workers.celery_app import celery_app

    try:
        parsed_id = _uuid.UUID(run_id)
    except ValueError:
        return RedirectResponse(
            url="/dashboard/monitor?error=Invalid+run+ID",
            status_code=303,
        )

    run_repo = AgentRunRepository(db)
    run = await run_repo.get_by_id(parsed_id)
    if not run:
        return RedirectResponse(
            url="/dashboard/monitor?error=Run+not+found",
            status_code=303,
        )

    # Set cancellation flag in Redis
    EventEmitter.request_cancel(run.id)

    # Revoke Celery task
    if run.celery_task_id:
        celery_app.control.revoke(run.celery_task_id, terminate=True, signal="SIGTERM")

    # Update status in DB
    run.status = AgentRunStatus.CANCELLED
    run.completed_at = datetime.utcnow()
    await db.commit()

    return RedirectResponse(
        url="/dashboard/monitor?success=Run+cancelled",
        status_code=303,
    )


@router.post("/dashboard/monitor/stop-all")
async def monitor_stop_all(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Stop all running agent runs (admin-only)."""
    user = await _get_current_user_from_cookie(request, db)
    if not user or not user.is_admin:
        return RedirectResponse(
            url="/dashboard/login?error=Admin+login+required",
            status_code=303,
        )

    from exnot.ai.event_emitter import EventEmitter
    from exnot.workers.celery_app import celery_app

    run_repo = AgentRunRepository(db)
    active_runs = await run_repo.get_active()

    cancelled_count = 0
    for run in active_runs:
        EventEmitter.request_cancel(run.id)
        if run.celery_task_id:
            celery_app.control.revoke(run.celery_task_id, terminate=True, signal="SIGTERM")
        run.status = AgentRunStatus.CANCELLED
        run.completed_at = datetime.utcnow()
        cancelled_count += 1

    await db.commit()

    return RedirectResponse(
        url=f"/dashboard/monitor?success=Cancelled+{cancelled_count}+run(s)",
        status_code=303,
    )


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
