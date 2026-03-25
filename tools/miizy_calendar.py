#!/usr/bin/env python3
"""
Créneaux Google Calendar pour l'agent Miizy (Alex).
- Token : miizy_token.json
- 12h minimum d'avance
- Lundi–Vendredi uniquement
- Créneaux : 9h00, 10h30, 14h00, 15h30, 17h00
"""
import json
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger("miizy_calendar")

_BASE = Path(__file__).parent.parent
MIIZY_TOKEN_FILE  = _BASE / "miizy_token.json"
MIIZY_CREDS_FILE  = _BASE / "miizy_credentials.json"
MIIZY_CALENDAR_ID = "primary"

JOURS_FR     = ["lundi", "mardi", "mercredi", "jeudi", "vendredi"]
SLOT_HOURS   = [(9, 0), (10, 30), (14, 0), (15, 30), (17, 0)]
ADVANCE_HOURS = 12  # minimum d'avance


def _slot_label(day_dt: datetime, h: int, m: int) -> str:
    jour_str = JOURS_FR[day_dt.weekday()]
    date_str = day_dt.strftime("%d/%m")
    return f"{jour_str} {date_str} à {h}h{m:02d}" if m else f"{jour_str} {date_str} à {h}h"


def _get_service():
    """Initialise le service Calendar Miizy via miizy_token.json."""
    try:
        if not MIIZY_TOKEN_FILE.exists():
            logger.warning("[Miizy Calendar] miizy_token.json absent — autorisation requise")
            return None
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
        data = json.loads(MIIZY_TOKEN_FILE.read_text())
        creds = Credentials(
            token=data.get("token"),
            refresh_token=data.get("refresh_token"),
            token_uri=data.get("token_uri"),
            client_id=data.get("client_id"),
            client_secret=data.get("client_secret"),
            scopes=data.get("scopes"),
        )
        service = build("calendar", "v3", credentials=creds)
        logger.info("[Miizy Calendar] Connecté via OAuth2")
        return service
    except Exception as e:
        logger.warning(f"[Miizy Calendar] Erreur connexion: {e}")
        return None


def _get_busy(service, days: int = 14) -> List[Tuple[datetime, datetime]]:
    try:
        now = datetime.now()
        body = {
            "timeMin": now.isoformat() + "Z",
            "timeMax": (now + timedelta(days=days)).isoformat() + "Z",
            "items": [{"id": MIIZY_CALENDAR_ID}],
        }
        result = service.freebusy().query(body=body).execute()
        busy = result.get("calendars", {}).get(MIIZY_CALENDAR_ID, {}).get("busy", [])
        return [
            (datetime.fromisoformat(b["start"].replace("Z", "")),
             datetime.fromisoformat(b["end"].replace("Z", "")))
            for b in busy
        ]
    except Exception as e:
        logger.warning(f"[Miizy Calendar] Freebusy erreur: {e}")
        return []


def _is_free(slot_dt: datetime, busy: List[Tuple]) -> bool:
    slot_end = slot_dt + timedelta(minutes=30)
    for s, e in busy:
        if slot_dt < e and slot_end > s:
            return False
    return True


def get_miizy_slots(count: int = 3, exclude: List[str] = None) -> List[str]:
    """
    Retourne les `count` prochains créneaux disponibles pour Miizy.
    - Minimum 12h d'avance
    - Lundi–Vendredi uniquement
    - Vérifie les dispo Google Calendar si token présent
    """
    exclude = exclude or []
    exclude_lower = [e.lower() for e in exclude]
    now = datetime.now()
    min_time = now + timedelta(hours=ADVANCE_HOURS)

    busy = []
    service = _get_service()
    if service:
        busy = _get_busy(service)

    slots = []
    for offset in range(0, 21):
        if len(slots) >= count:
            break
        candidate = (now + timedelta(days=offset)).replace(second=0, microsecond=0)
        if candidate.weekday() >= 5:  # week-end
            continue
        for (h, m) in SLOT_HOURS:
            if len(slots) >= count:
                break
            slot_dt = candidate.replace(hour=h, minute=m)
            if slot_dt < min_time:
                continue
            label = _slot_label(candidate, h, m)
            if label.lower() in exclude_lower:
                continue
            if busy and not _is_free(slot_dt, busy):
                continue
            slots.append(label)

    logger.info(f"[Miizy Calendar] Créneaux: {slots}")
    return slots


def detect_chosen_slot(txt: str, slots: List[str]) -> Optional[str]:
    """
    Détecte quel créneau le prospect a choisi parmi une liste.
    Essaie la correspondance directe puis les ordinaux (premier, deuxième…).
    """
    t = txt.lower().strip()

    # Correspondance directe : si un label apparaît dans le texte
    for slot in slots:
        for part in slot.lower().split():
            if len(part) >= 4 and part in t:
                return slot

    # Heure mentionnée (ex: "10h", "15h30", "9h")
    heure_m = re.search(r'\b(\d{1,2})h(\d{0,2})\b', t)
    if heure_m:
        h = int(heure_m.group(1))
        m = int(heure_m.group(2)) if heure_m.group(2) else 0
        for slot in slots:
            if f"{h}h{m:02d}" in slot.lower() or (m == 0 and f"{h}h" in slot.lower()):
                return slot

    # Ordinaux
    ordinals = [
        (["premier", "première", "1er", "1ère", "le 1", "le premier", "le 1er", "1"], 0),
        (["deuxième", "2ème", "second", "le 2", "le deuxième", "2"], 1),
        (["troisième", "3ème", "le 3", "le troisième", "3"], 2),
    ]
    for keywords, idx in ordinals:
        if any(kw in t for kw in keywords) and idx < len(slots):
            return slots[idx]

    return None


def create_miizy_event(phone: str, slot_label: str, prenom: str = "") -> bool:
    """Crée un rappel dans le Calendar Miizy pour ce RDV."""
    service = _get_service()
    if not service:
        logger.warning("[Miizy Calendar] Pas de service — RDV non créé")
        return False
    try:
        date_m = re.search(r'(\d{1,2})/(\d{1,2})', slot_label)
        heure_m = re.search(r'(\d{1,2})h(\d{0,2})', slot_label)
        if not date_m or not heure_m:
            return False
        day, month = int(date_m.group(1)), int(date_m.group(2))
        hour = int(heure_m.group(1))
        minute = int(heure_m.group(2)) if heure_m.group(2) else 0
        year = datetime.now().year
        start_dt = datetime(year, month, day, hour, minute)
        end_dt   = start_dt + timedelta(minutes=30)
        nom = prenom or phone
        event = {
            "summary": f"📞 Démo Miizy — {nom}",
            "description": f"Démo Miizy 20 min\nContact : {nom}\nTél : {phone}",
            "start": {"dateTime": start_dt.isoformat(), "timeZone": "Europe/Paris"},
            "end":   {"dateTime": end_dt.isoformat(),   "timeZone": "Europe/Paris"},
            "colorId": "2",
            "reminders": {"useDefault": False, "overrides": [
                {"method": "popup", "minutes": 15},
                {"method": "email", "minutes": 60},
            ]},
        }
        service.events().insert(calendarId=MIIZY_CALENDAR_ID, body=event).execute()
        logger.info(f"[Miizy Calendar] Événement créé: {slot_label} pour {nom}")
        return True
    except Exception as e:
        logger.error(f"[Miizy Calendar] Erreur création événement: {e}")
        return False
