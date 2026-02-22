"""
Lokale SQLite-Datenbank für den Offline-Betrieb der Kasse.

Speichert:
- CachedMember:   Mitglieder-Cache (RFID → Name + ID)
- CachedProduct:  Produkt-Cache (Barcode → Name + Preis)
- PendingBooking: Buchungen, die noch nicht an den Server übermittelt wurden
"""
import json
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import Boolean, Column, DateTime, Numeric, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


class CachedMember(Base):
    __tablename__ = "cached_members"

    id = Column(String(36), primary_key=True)
    name = Column(String(200), nullable=False)
    rfid_token = Column(String(100), unique=True, nullable=True)
    synced_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    def __repr__(self) -> str:
        return f"<CachedMember {self.name} rfid={self.rfid_token}>"


class CachedProduct(Base):
    __tablename__ = "cached_products"

    id = Column(String(36), primary_key=True)
    name = Column(String(200), nullable=False)
    barcode = Column(String(50), unique=True, nullable=True)
    price = Column(Numeric(10, 2), nullable=False)
    synced_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    def __repr__(self) -> str:
        return f"<CachedProduct {self.name} barcode={self.barcode} price={self.price}>"


class PendingBooking(Base):
    """Eine Buchung, die lokal gespeichert und später synchronisiert wird."""
    __tablename__ = "pending_bookings"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    member_id = Column(String(36), nullable=False)
    # JSON-Liste: [{"product_id": "...", "quantity": 1, "unit_price": "2.50"}, ...]
    items_json = Column(Text, nullable=False)
    total_price = Column(Numeric(10, 2), nullable=False)
    booked_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    synced = Column(Boolean, default=False, nullable=False)

    @property
    def items(self) -> list[dict]:
        return json.loads(self.items_json)


# ---------------------------------------------------------------------------
# Engine + Session
# ---------------------------------------------------------------------------

_engine = create_engine(
    f"sqlite:///{settings.local_db_path}",
    connect_args={"check_same_thread": False},
    echo=False,
)
Base.metadata.create_all(_engine)

_SessionFactory = sessionmaker(bind=_engine, expire_on_commit=False)


@contextmanager
def get_session():
    """Context-Manager für eine DB-Session mit automatischem Commit/Rollback."""
    session: Session = _SessionFactory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def find_member_by_rfid(rfid_token: str) -> CachedMember | None:
    with get_session() as db:
        return db.query(CachedMember).filter_by(rfid_token=rfid_token).first()


def find_product_by_barcode(barcode: str) -> CachedProduct | None:
    with get_session() as db:
        return db.query(CachedProduct).filter_by(barcode=barcode).first()


def save_pending_booking(
    member_id: str,
    items: list[dict],
    total_price: Decimal,
    booked_at: datetime | None = None,
) -> PendingBooking:
    with get_session() as db:
        booking = PendingBooking(
            member_id=member_id,
            items_json=json.dumps(items),
            total_price=total_price,
            booked_at=booked_at or datetime.now(timezone.utc),
        )
        db.add(booking)
    return booking


def get_pending_bookings() -> list[PendingBooking]:
    with get_session() as db:
        return db.query(PendingBooking).filter_by(synced=False).all()


def mark_bookings_synced(booking_ids: list[str]) -> None:
    with get_session() as db:
        db.query(PendingBooking).filter(
            PendingBooking.id.in_(booking_ids)
        ).update({"synced": True}, synchronize_session=False)


def replace_member_cache(members: list[dict]) -> None:
    with get_session() as db:
        db.query(CachedMember).delete()
        for m in members:
            db.add(CachedMember(
                id=m["id"],
                name=m["name"],
                rfid_token=m.get("rfid_token"),
            ))


def replace_product_cache(products: list[dict]) -> None:
    with get_session() as db:
        db.query(CachedProduct).delete()
        for p in products:
            db.add(CachedProduct(
                id=p["id"],
                name=p["name"],
                barcode=p.get("barcode"),
                price=Decimal(str(p["price"])),
            ))
