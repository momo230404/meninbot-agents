#!/usr/bin/env python3
"""
Google Calendar API - Créneaux réels + fallback intelligent
Structure des créneaux :
  C1 : prochain créneau matin (9h-12h)  — Jour A
  C2 : créneau après-midi (14h-18h)     — Jour A (ou jour A+1 si plus dispo)
  C3 : premier créneau du jour ouvré suivant le Jour A
"""
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Tuple

logger = logging.getLogger(__name__)
CONFIG = json.load(open(Path(__file__).parent.parent / "config.json"))
CALENDAR_ID = CONFIG.get("google", {}).get("calendar_id", "primary")
CREDENTIALS_FILE = Path(__file__).parent.parent / CONFIG.get("google", {}).get("credentials_file", "client_secret_gdrive.json")
OAUTH_TOKEN_FILE = Path(__file__).parent.parent / "token.json"
OAUTH_CREDS_FILE = Path(__file__).parent.parent / "oauth_credentials.json"

CALENDAR_SCOPES = [
    'https://www.googleapis.com/auth/calendar',
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive',
]

JOURS_FR = ["lundi", "mardi", "mercredi", "jeudi", "vendredi"]
MORNING_HOURS  = [(9, 0), (10, 30)]              # 9h00 et 10h30
AFTERNOON_HOURS = [(14, 0), (15, 30), (17, 0)]  # 14h00, 15h30, 17h00


def _slot_label(day_dt: datetime, heure: int, minute: int) -> str:
    """Formate un créneau : 'lundi 17/03 à 9h00' ou 'lundi 17/03 à 10h30'"""
    jour_str = JOURS_FR[day_dt.weekday()]
    date_str = day_dt.strftime("%d/%m")
    if minute:
        return f"{jour_str} {date_str} à {heure}h{minute:02d}"
    return f"{jour_str} {date_str} à {heure}h00"


def _get_calendar_service():
    """Initialise le service Calendar via OAuth2 token existant."""
    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        if not OAUTH_TOKEN_FILE.exists():
            return None
        token_data = json.loads(OAUTH_TOKEN_FILE.read_text())
        scopes = token_data.get("scopes", [])
        has_calendar = any("calendar" in s for s in scopes)
        if not has_calendar:
            logger.warning("Token OAuth2 sans scope calendar — fallback sur créneaux générés")
            return None

        creds = Credentials(
            token=token_data.get("token"),
            refresh_token=token_data.get("refresh_token"),
            token_uri=token_data.get("token_uri"),
            client_id=token_data.get("client_id"),
            client_secret=token_data.get("client_secret"),
            scopes=scopes,
        )
        service = build('calendar', 'v3', credentials=creds)
        logger.info("Google Calendar connecté via OAuth2")
        return service
    except Exception as e:
        logger.warning(f"Calendar non disponible: {e}")
        return None


def _get_busy_slots(service, days: int = 14) -> List[Tuple[datetime, datetime]]:
    """Récupère les plages occupées via freebusy."""
    try:
        now = datetime.now()
        time_min = now.isoformat() + 'Z'
        time_max = (now + timedelta(days=days)).isoformat() + 'Z'
        body = {
            "timeMin": time_min,
            "timeMax": time_max,
            "items": [{"id": CALENDAR_ID}]
        }
        result = service.freebusy().query(body=body).execute()
        busy = result.get("calendars", {}).get(CALENDAR_ID, {}).get("busy", [])
        return [(datetime.fromisoformat(b["start"].replace("Z", "")),
                 datetime.fromisoformat(b["end"].replace("Z", ""))) for b in busy]
    except Exception as e:
        logger.warning(f"Freebusy error: {e}")
        return []


def _is_slot_free(slot_start: datetime, busy_slots: List[Tuple]) -> bool:
    slot_end = slot_start + timedelta(minutes=45)
    for busy_start, busy_end in busy_slots:
        if slot_start < busy_end and slot_end > busy_start:
            return False
    return True


def _next_business_day(from_date: datetime) -> datetime:
    """Retourne le prochain jour ouvré APRÈS from_date (jamais le même jour)."""
    d = from_date + timedelta(days=1)
    while d.weekday() >= 5:  # Skip weekend
        d += timedelta(days=1)
    return d


def _find_first_slot(day_dt: datetime, hours: list, now: datetime,
                     busy: list, exclude_lower: list) -> Optional[str]:
    """Cherche le premier créneau disponible parmi hours pour un jour donné."""
    for (h, m) in hours:
        slot_dt = day_dt.replace(hour=h, minute=m, second=0, microsecond=0)
        if slot_dt <= now:
            continue  # Passé
        label = _slot_label(day_dt, h, m)
        if label.lower() in exclude_lower:
            continue
        if busy and not _is_slot_free(slot_dt, busy):
            continue
        return label
    return None


def get_real_slots(days: int = 14, exclude: List[str] = None, count: int = 3) -> List[str]:
    """
    Retourne 3 créneaux structurés :
      C1 : prochain créneau matin (9h-12h)   — Jour A
      C2 : créneau après-midi (14h-18h)      — Jour A si dispo, sinon Jour A+1
      C3 : n'importe quel créneau du prochain jour ouvré APRÈS le Jour A
    Jamais de weekend. Appel Calendar API en temps réel si disponible.
    """
    exclude = exclude or []
    exclude_lower = [e.lower() for e in exclude]
    busy = []

    service = _get_calendar_service()
    if service:
        busy = _get_busy_slots(service, days)
        logger.info(f"Calendar: {len(busy)} plages occupées")

    now = datetime.now()
    result = []
    day_A = None  # Jour du C1

    # ── Créneau 1 : prochain créneau matin (aujourd'hui ou lendemain)
    for offset in range(0, days):
        candidate = now + timedelta(days=offset)
        if candidate.weekday() >= 5:
            continue
        slot = _find_first_slot(candidate, MORNING_HOURS, now, busy, exclude_lower)
        if slot:
            result.append(slot)
            day_A = candidate.replace(hour=0, minute=0, second=0, microsecond=0)
            break

    # ── Créneau 2 : après-midi du Jour A, sinon Jour A+1
    if day_A is not None:
        slot2 = _find_first_slot(day_A, AFTERNOON_HOURS, now, busy, exclude_lower)
        if slot2:
            result.append(slot2)
        else:
            # Chercher le lendemain
            day_A1 = _next_business_day(day_A)
            slot2 = _find_first_slot(day_A1, AFTERNOON_HOURS, now, busy, exclude_lower)
            if slot2:
                result.append(slot2)
                day_A = day_A1  # Mettre à jour le jour de référence

    # ── Créneau 3 : prochain jour ouvré APRÈS Jour A
    if day_A is not None:
        day_C3 = _next_business_day(day_A)
        slot3 = _find_first_slot(day_C3, MORNING_HOURS + AFTERNOON_HOURS, now, busy, exclude_lower)
        if slot3:
            result.append(slot3)

    # Fallback : si on n'a pas encore 3 créneaux, compléter simplement
    if len(result) < count:
        extra = _get_extra_slots(exclude=exclude + result, count=count - len(result),
                                 start_after=day_A, now=now, busy=busy)
        result.extend(extra)

    logger.info(f"Créneaux proposés: {result}")
    return result[:count]


def _get_extra_slots(exclude: list, count: int, start_after: Optional[datetime],
                     now: datetime, busy: list) -> List[str]:
    """Génère des créneaux supplémentaires pour compléter si nécessaire."""
    exclude_lower = [e.lower() for e in exclude]
    slots = []
    offset = 0
    while len(slots) < count and offset < 21:
        offset += 1
        candidate = now + timedelta(days=offset)
        if candidate.weekday() >= 5:
            continue
        if start_after and candidate.date() <= start_after.date():
            continue
        for (h, m) in MORNING_HOURS + AFTERNOON_HOURS:
            if len(slots) >= count:
                break
            slot_dt = candidate.replace(hour=h, minute=m, second=0, microsecond=0)
            if slot_dt <= now:
                continue
            label = _slot_label(candidate, h, m)
            if label.lower() in exclude_lower:
                continue
            if busy and not _is_slot_free(slot_dt, busy):
                continue
            slots.append(label)
    return slots


def get_slots_for_day(day_name: str, exclude: List[str] = None, count: int = 5) -> List[str]:
    """
    Retourne TOUS les créneaux disponibles pour un jour de semaine spécifique.
    Ex : get_slots_for_day("mercredi") → tous les créneaux mercredi disponibles.
    """
    exclude = exclude or []
    exclude_lower = [e.lower() for e in exclude]
    day_name_lower = day_name.lower().strip()

    try:
        target_weekday = JOURS_FR.index(day_name_lower)
    except ValueError:
        return get_real_slots(exclude=exclude, count=count)

    busy = []
    service = _get_calendar_service()
    if service:
        busy = _get_busy_slots(service, days=21)

    slots = []
    now = datetime.now()

    for day_offset in range(1, 22):
        if len(slots) >= count:
            break
        candidate = now + timedelta(days=day_offset)
        if candidate.weekday() != target_weekday:
            continue

        for (h, m) in MORNING_HOURS + AFTERNOON_HOURS:
            if len(slots) >= count:
                break
            slot_dt = candidate.replace(hour=h, minute=m, second=0, microsecond=0)
            label = _slot_label(candidate, h, m)
            if label.lower() in exclude_lower:
                continue
            if busy and not _is_slot_free(slot_dt, busy):
                continue
            slots.append(label)

        break  # On ne cherche que la prochaine occurrence du jour

    logger.info(f"Créneaux {day_name}: {slots}")
    return slots


def create_calendar_event(email: str, phone: str, slot_label: str, prenom: str = "") -> Optional[str]:
    """
    Crée un événement Google Calendar avec Google Meet.
    Retourne le lien Meet si succès, None sinon.
    """
    service = _get_calendar_service()
    if not service:
        logger.warning("Calendar non disponible — RDV non créé dans l'agenda")
        return None

    try:
        import re
        date_m = re.search(r'(\d{1,2})/(\d{1,2})', slot_label)
        heure_m = re.search(r'(\d{1,2})h(\d{0,2})', slot_label)
        if not date_m or not heure_m:
            return None

        day, month = int(date_m.group(1)), int(date_m.group(2))
        hour = int(heure_m.group(1))
        minute = int(heure_m.group(2)) if heure_m.group(2) else 0
        year = datetime.now().year
        start_dt = datetime(year, month, day, hour, minute)
        end_dt = start_dt + timedelta(minutes=45)

        nom = prenom or "prospect"
        event = {
            'summary': f'RDV Vianova – {nom}',
            'description': f'RDV avec {nom}\nTél: {phone}\nCréneau: {slot_label}',
            'start': {'dateTime': start_dt.isoformat(), 'timeZone': 'Europe/Paris'},
            'end':   {'dateTime': end_dt.isoformat(),   'timeZone': 'Europe/Paris'},
            'attendees': [{'email': email}] if email else [],
            'conferenceData': {
                'createRequest': {
                    'requestId': f"vianova-{phone}-{int(start_dt.timestamp())}",
                    'conferenceSolutionKey': {'type': 'hangoutsMeet'}
                }
            },
            'reminders': {'useDefault': False, 'overrides': [
                {'method': 'email', 'minutes': 60},
                {'method': 'popup', 'minutes': 15},
            ]},
        }

        created = service.events().insert(
            calendarId=CALENDAR_ID,
            body=event,
            conferenceDataVersion=1,
            sendUpdates='all'
        ).execute()

        meet_link = created.get('conferenceData', {}).get('entryPoints', [{}])[0].get('uri', '')
        logger.info(f"RDV créé: {created.get('htmlLink')} | Meet: {meet_link}")
        return meet_link or created.get('htmlLink', '')

    except Exception as e:
        logger.error(f"Erreur création RDV Calendar: {e}")
        return None


# Instance legacy compat
class GoogleCalendarAPI:
    def get_available_slots(self, days=7, exclude=None):
        return get_real_slots(days=days, exclude=exclude or [], count=9)

    def create_event(self, email, phone, creneau, summary=None, prenom=""):
        link = create_calendar_event(email, phone, creneau, prenom)
        return link is not None

calendar_api = GoogleCalendarAPI()
