"""Subscriber management API endpoints."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from exnot.api.deps import require_auth
from exnot.api.schemas import SubscriberCreate, SubscriberResponse
from exnot.db.engine import get_db
from exnot.db.models import NotificationFrequency, Subscriber, User
from exnot.db.repositories import SubscriberRepository

router = APIRouter(prefix="/subscribers", tags=["subscribers"])


@router.post("", response_model=SubscriberResponse, status_code=201)
async def create_subscriber(
    data: SubscriberCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new email subscription for fee change alerts."""
    repo = SubscriberRepository(db)

    existing = await repo.get_by_email(data.email)
    if existing:
        raise HTTPException(status_code=409, detail="Email already subscribed")

    subscriber = Subscriber(
        email=data.email,
        name=data.name,
        exchanges_filter=data.exchanges_filter,
        notification_frequency=NotificationFrequency(data.notification_frequency),
    )
    subscriber = await repo.create(subscriber)
    await db.commit()

    return SubscriberResponse(
        id=subscriber.id,
        email=subscriber.email,
        name=subscriber.name,
        is_active=subscriber.is_active,
        exchanges_filter=subscriber.exchanges_filter,
        notification_frequency=subscriber.notification_frequency.value,
        created_at=subscriber.created_at,
    )


@router.put("/{subscriber_id}", response_model=SubscriberResponse)
async def update_subscriber(
    subscriber_id: uuid.UUID,
    data: SubscriberCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_auth),
):
    """Update subscription preferences."""
    repo = SubscriberRepository(db)
    subscriber = await repo.get_by_email(data.email)
    if not subscriber or subscriber.id != subscriber_id:
        raise HTTPException(status_code=404, detail="Subscriber not found")

    subscriber.name = data.name
    subscriber.exchanges_filter = data.exchanges_filter
    subscriber.notification_frequency = NotificationFrequency(data.notification_frequency)
    await db.commit()

    return SubscriberResponse(
        id=subscriber.id,
        email=subscriber.email,
        name=subscriber.name,
        is_active=subscriber.is_active,
        exchanges_filter=subscriber.exchanges_filter,
        notification_frequency=subscriber.notification_frequency.value,
        created_at=subscriber.created_at,
    )


@router.delete("/{subscriber_id}", status_code=204)
async def delete_subscriber(
    subscriber_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Unsubscribe (deactivate) a subscriber."""
    from sqlalchemy import select

    stmt = select(Subscriber).where(Subscriber.id == subscriber_id)
    result = await db.execute(stmt)
    subscriber = result.scalar_one_or_none()

    if not subscriber:
        raise HTTPException(status_code=404, detail="Subscriber not found")

    subscriber.is_active = False
    await db.commit()
