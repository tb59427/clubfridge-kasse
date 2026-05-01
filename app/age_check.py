"""Lokale Jugendschutz-Prüfung in der Kasse.

Verwendet den vom Server gelieferten und lokal gecachten Stand:
- Konfiguration: enabled + limits (kategorie → mindest-alter)
- Mitglieds-Geburtsdatum: aus CachedMember
- Produkt-Kategorie: aus CachedProduct.age_category
"""

from __future__ import annotations

from datetime import date

from app.local_db import CachedMember, CachedProduct, get_cached_age_check_config


def _calculate_age(birthday: date, today: date) -> int:
    age = today.year - birthday.year
    if (today.month, today.day) < (birthday.month, birthday.day):
        age -= 1
    return age


def check_age_for_purchase(
    *,
    purchaser: CachedMember,
    products: list[CachedProduct],
    today: date | None = None,
) -> str | None:
    """Prüft ob das Mitglied alle Produkte erwerben darf.

    Returns:
        None wenn alles OK ist (oder Prüfung deaktiviert)
        Fehlertext (Deutsch) wenn ein Produkt blockiert ist
    """
    cfg = get_cached_age_check_config()
    if not cfg.get("enabled"):
        return None

    # Sonderkonten werden vom Check ausgenommen — keine Personen, sondern
    # Sammelkonten (z.B. „Vorstandssitzung").
    if getattr(purchaser, "is_billing_account", False):
        return None

    relevant = [p for p in products if (p.age_category or "none") != "none"]
    if not relevant:
        return None

    limits: dict[str, int] = cfg.get("limits", {}) or {}
    today = today or date.today()

    if purchaser.birthday is None:
        return (
            "Geburtsdatum nicht hinterlegt — Kauf alkoholischer Produkte nicht möglich.\n"
            "Bitte einen Admin bitten, das Datum zu ergänzen."
        )

    age = _calculate_age(purchaser.birthday, today)
    blocked: list[tuple[CachedProduct, int]] = []
    for p in relevant:
        required = limits.get(p.age_category)
        if required is None:
            continue
        if age < required:
            blocked.append((p, required))

    if not blocked:
        return None

    names = ", ".join(p.name for p, _ in blocked)
    max_required = max(req for _, req in blocked)
    return (
        f'Altersbeschränkung: für „{names}" ist ein Mindestalter von '
        f"{max_required} Jahren erforderlich."
    )
