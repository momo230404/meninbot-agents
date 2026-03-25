#!/usr/bin/env python3
"""
Agent Vianova V5 - Fix extraction typo/ville + confirmation créneaux robuste
"""
import json
import logging
import random
import re
from datetime import datetime
from pathlib import Path
from typing import Tuple, Optional

from conversation_memory import ConversationMemory
from tools.vianova_api import get_stock
from tools.calendar_api import get_real_slots, get_slots_for_day, create_calendar_event
from tools.off_context import detect_off_context, off_context_response, context_recovery, detect_loop, store_response

logger = logging.getLogger(__name__)

# ── Loader scénarios éditables ───────────────────────────────────────────────
def _sc_get(key: str, idx: int = None):
    """Charge les réponses depuis agent_scenarios.json (fallback: None)"""
    try:
        p = Path(__file__).parent / 'agent_scenarios.json'
        if p.exists():
            d = json.loads(p.read_text())
            responses = d.get('scenarios', {}).get(key, {}).get('responses', [])
            if responses:
                if idx is not None:
                    return responses[idx] if idx < len(responses) else responses[0]
                return responses
    except Exception:
        pass
    return None

# ── Typologies ──────────────────────────────────────────────────────────────
# Gère: T2, F3, t2, "T 2", "2 pièces", studio, appartement, maison, villa
TYPO_PATTERNS = re.compile(
    r'''(?xi)
    \b(
        t\s*[1-5]                          # T2, T3, T 2
      | f\s*[1-5]                          # F3, F2 (normalisé en T)
      | studio
      | [1-5]\s*pi[eèé]ces?               # 2 pièces, 3 pieces
      | (?:un\s+)?deux\s+pi[eèé]ces?     # deux pièces, un deux pièces
      | trois\s+pi[eèé]ces?               # trois pièces
      | quatre\s+pi[eèé]ces?              # quatre pièces
      | cinq\s+pi[eèé]ces?               # cinq pièces
      | appartement
      | maison
      | villa
    )\b''',
    re.IGNORECASE | re.UNICODE
)

JOURS_FR_VARIANTS = {
    "lundi": "lundi", "lundis": "lundi",
    "mardi": "mardi", "mardis": "mardi",
    "mercredi": "mercredi", "mercredis": "mercredi",
    "jeudi": "jeudi", "jeudis": "jeudi",
    "vendredi": "vendredi", "vendredis": "vendredi",
}


def _normalize_typo(raw: str) -> Optional[str]:
    """Normalise une chaîne brute extraite vers T1-T5."""
    import unicodedata
    # 1. Supprimer les accents (PIÈCES → PIECES)
    raw_no_acc = ''.join(
        c for c in unicodedata.normalize('NFD', raw.upper().strip())
        if unicodedata.category(c) != 'Mn'
    )
    # 2. Normaliser les espaces
    raw_c = re.sub(r'\s+', ' ', raw_no_acc).strip()
    # 3. Mots numéraux → chiffre
    word_to_n = {
        "UN DEUX": 2, "DEUX": 2,
        "TROIS": 3, "QUATRE": 4, "CINQ": 5, "UN": 1,
    }
    for word, n in word_to_n.items():
        if word in raw_c:
            return f"T{n}"
    # 4. F→T (F3 → T3)
    raw_c = re.sub(r'^F\s*([1-5])$', r'T\1', raw_c)
    # 5. T 2 → T2
    raw_c = re.sub(r'^T\s*([1-5])$', r'T\1', raw_c)
    # 6. Mapping direct
    mapping = {
        "STUDIO": "T1", "APPARTEMENT": None, "MAISON": None, "VILLA": None,
        "1 PIECE": "T1",  "1 PIECES": "T1",  "1PIECE": "T1",
        "2 PIECES": "T2", "2PIECES": "T2",
        "3 PIECES": "T3", "3PIECES": "T3",
        "4 PIECES": "T4", "4PIECES": "T4",
        "5 PIECES": "T5", "5PIECES": "T5",
    }
    if raw_c in mapping:
        return mapping[raw_c]
    # 7. Déjà T1-T5
    if re.match(r'^T[1-5]$', raw_c):
        return raw_c
    return None


def _extract_typo(text: str) -> Optional[str]:
    """Extrait une typologie depuis un texte libre.
    Gère: T2, T 2, F3, 2 pièces, deux pièces, un deux pièces, studio, etc.
    """
    m = TYPO_PATTERNS.search(text)
    if not m:
        return None
    return _normalize_typo(m.group(1))


_CITIES_CACHE = None

def _get_cities_index():
    """Retourne un dict {nom_lower: nom_original} des villes Miizy"""
    global _CITIES_CACHE
    if _CITIES_CACHE is None:
        try:
            from tools.vianova_api import api as miizy_api
            cities = miizy_api.get_cities()
            _CITIES_CACHE = {}
            for c in cities:
                name = c.get("name", "")
                slug = c.get("slug", "")
                if name:
                    _CITIES_CACHE[name.lower()] = name
                if slug:
                    _CITIES_CACHE[slug.lower().replace("-", " ")] = name
        except Exception:
            _CITIES_CACHE = {}
    return _CITIES_CACHE


def _extract_ville(text: str) -> Optional[str]:
    """Extrait un nom de ville depuis un texte libre.
    Règle : retourne None UNIQUEMENT si le texte entier est une typologie pure.
    Ex: "T3" → None, "T3 bordeaux" → "Bordeaux", "Lille t2" → "Lille"
    """
    txt = text.strip()
    # Retourner None seulement si le texte EST exclusivement une typologie
    if re.match(r'^[TtFf]\s*[1-5]\s*$', txt):
        return None
    if re.match(r'^[1-5]\s*pi[eèé]ces?\s*$', txt, re.IGNORECASE):
        return None
    if re.match(r'^(?:un\s+)?(?:deux|trois|quatre|cinq)\s+pi[eèé]ces?\s*$', txt, re.IGNORECASE):
        return None
    if re.match(r'^(studio|appartement|maison|villa)\s*$', txt, re.IGNORECASE):
        return None

    cities_index = _get_cities_index()

    # Enlever les typologies du texte avant la recherche de ville
    txt_clean = TYPO_PATTERNS.sub(' ', txt).strip()
    txt_clean = re.sub(r'\s+', ' ', txt_clean).strip()

    # Chercher dans l'index Miizy (plus fiable)
    for search_txt in [txt_clean, txt]:
        words = search_txt.lower().split()
        for size in range(min(4, len(words)), 0, -1):
            for start in range(len(words) - size + 1):
                candidate = " ".join(words[start:start + size])
                candidate_dash = candidate.replace(" ", "-")
                if candidate in cities_index:
                    return cities_index[candidate]
                if candidate_dash in cities_index:
                    return cities_index[candidate_dash]

    # Fallback heuristique sur le texte nettoyé
    txt_h = re.sub(r'[,;.!?]', ' ', txt_clean).strip()
    txt_h = re.sub(r'\s+', ' ', txt_h)
    words = txt_h.lower().split()

    STOPWORDS = {'oui','non','ok','merci','bonjour','salut','pas','plus','je',
                 'il','elle','nous','vous','ils','toujours','encore','bien','plutôt','plutot',
                 'sur','super','exactement','effectivement','parfait','voila','voilà',
                 'de','du','le','la','les','un','une','en','et','ou','a','à','au','aux',
                 'pour','avec','dans','par','chez','vers','près','pres','me','ma','mon',
                 'parle','parlais','cherche','cherchais','veux','voudrais','intéressé',
                 'interesse','nouveau','nouveaux','critères','criteres',
                 # Formules de politesse — jamais des noms de villes
                 'retour','rappel','suivi','contact','message','courrier','reponse',
                 'réponse','bonsoir','bonne','journée','journee','soiree','soirée',
                 'info','infos','cordialement','sincèrement','sincerement','amicalement',
                 'nouvelles','appel','relance','échange','echange',
                 'finalement','linstant','instant','moment','actuellement',
                 'justement','maintenant','toute','fois','quand',
                 'meme','même','depuis','pendant','avant','après','apres',
                 'trouve','trouvé','entre','temps','jai','mai','cela','cest',
                 'tres','tout','trop','coup','fait','juste','vraiment','merci'}

    if 1 <= len(words) <= 4:
        clean_words = [w for w in words if w not in STOPWORDS]
        if clean_words:
            result = ' '.join(w for w in txt_h.split() if w.lower() not in STOPWORDS)
            if result:
                return '-'.join(p.capitalize() for p in result.title().split('-'))

    original_words = txt_h.split()
    candidates = []
    for i, w in enumerate(original_words):
        w_clean = re.sub(r"[^a-zA-ZÀ-ÿ\-]", "", w)
        if (len(w_clean) >= 3 and w_clean.lower() not in STOPWORDS
                and not re.match(r'^\d', w_clean)):
            group = w_clean
            for j in range(i+1, min(i+3, len(original_words))):
                next_w = re.sub(r'[^a-zA-ZÀ-ÿ\-]', '', original_words[j])
                if len(next_w) >= 2 and next_w.lower() not in STOPWORDS:
                    group += ' ' + next_w
                else:
                    break
            if group.lower() in cities_index:
                return cities_index[group.lower()]
            if group.lower().replace(' ', '-') in cities_index:
                return cities_index[group.lower().replace(' ', '-')]
            if len(w_clean) >= 3:
                candidates.append(w_clean.capitalize())

    for c in candidates:
        if len(c) >= 4:
            return c

    return None


_POLITE_RE = re.compile(
    r'(?i)'
    r'(bonjour|bonsoir|salut)\s*[,.\s!]*'
    r'|merci\s+(pour\s+)?(ce\s+|votre\s+|le\s+|mon\s+)?'
    r'(retour|rappel|message|suivi|contact|courrier|r[eé]ponse|appel|[eé]change)\s*[,.\s!]*'
    r'|merci(\s+(beaucoup|bien|infiniment|[àa]\s+vous))?\s*[,.\s!]+'
    r'|bonne\s+(journ[eé]e|soir[eé]e|continuation|semaine)\s*[,.\s!]*'
    r'|cordialement\s*[,.\s!]*'
    r'|avec\s+plaisir\s*[,.\s!]*'
    r'|bien\s+[àa]\s+vous\s*[,.\s!]*'
)

def _clean_polite(text: str) -> str:
    """Supprime les formules de politesse avant extraction ville/typo.
    Remplace aussi les apostrophes par des espaces pour éviter m'intéresse → 'minteresse'.
    """
    cleaned = _POLITE_RE.sub(' ', text)
    cleaned = re.sub(r"['\u2019\u2018]", " ", cleaned)  # apostrophes → espace
    return re.sub(r'\s+', ' ', cleaned).strip()


def _parse_ville_typo_from_lines(text: str):
    """Extrait ville + typo depuis un texte (multi-lignes possible)."""
    typo = _extract_typo(text)
    ville = _extract_ville(text)

    if not ville or not typo:
        lines = [l.strip() for l in text.replace(",", "\n").split("\n") if l.strip()]
        for line in lines:
            if not typo:
                typo = _extract_typo(line)
            if not ville:
                ville = _extract_ville(line)

    return ville, typo


EMAIL_RE = re.compile(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}')

def _detect_email(text: str) -> Optional[str]:
    m = EMAIL_RE.search(text)
    return m.group(0) if m else None


def _extract_requested_day(txt: str) -> Optional[str]:
    """Extrait un jour de semaine mentionné dans le texte (lundi..vendredi)."""
    txt_lower = txt.lower()
    for variant, canonical in JOURS_FR_VARIANTS.items():
        if re.search(r'\b' + variant + r'\b', txt_lower):
            return canonical
    return None


def _detect_slot_from_proposed(txt: str, active_slots: list) -> Optional[str]:
    """
    Détecte un créneau PRÉCIS parmi les slots actifs proposés.
    Ordre de priorité : ordinal > 2+ tokens communs > heure seule > date partielle.
    NE fait JAMAIS de fallback par défaut.
    """
    if not active_slots:
        return None
    txt_lower = txt.lower()

    # 1. Ordinal explicite (premier, deuxième...)
    ordinal_map = {
        "premier": 0, "1er": 0, "première": 0,
        "deuxième": 1, "2ème": 1, "2e ": 1, "second": 1, "seconde": 1,
        "troisième": 2, "3ème": 2, "3e ": 2,
    }
    for word, idx in ordinal_map.items():
        if word in txt_lower and idx < len(active_slots):
            return active_slots[idx]

    # 2. Correspondance forte : ≥2 tokens significatifs du slot présents dans le message
    #    Ex : "lundi 23 mars à 10h" → tokens ["lun","23","mar","10h"] ≥2 matches → sélection directe
    for slot in active_slots:
        slot_lower = slot.lower()
        tokens = [t for t in re.split(r'[\s,àéèê]+', slot_lower) if len(t) >= 2]
        matched = sum(1 for t in tokens if t in txt_lower)
        if matched >= 2:
            return slot

    # 3. Heure précise seule (ex: "10h30", "14h") — uniquement si un seul slot matche
    time_matches = re.findall(r'\b(\d{1,2}h\d{0,2})\b', txt_lower)
    for t in time_matches:
        matched_slots = [s for s in active_slots if t.lower() in s.lower()]
        if len(matched_slots) == 1:
            return matched_slots[0]

    # 4. Date partielle (ex: "le 23", "23 mars")
    date_m = re.search(r'\b(\d{1,2})\s*(jan|fév|mar|avr|mai|juin|juil|ao[uû]t|sep|oct|nov|d[eé]c)', txt_lower)
    if date_m:
        for slot in active_slots:
            if date_m.group(0) in slot.lower():
                return slot

    # Jour + heure tous les deux présents
    for slot in active_slots:
        slot_lower = slot.lower()
        day_m = re.match(r'^(\w+)', slot_lower)
        time_m = re.search(r'(\d+h\d*)', slot_lower)
        if day_m and time_m:
            if day_m.group(1) in txt_lower and time_m.group(1) in txt_lower:
                return slot

    return None


class VianovaAgent:
    """Daniel, conseiller Vianova"""

    def __init__(self, phone: str):
        self.phone = phone
        self.memory = ConversationMemory(phone)
        self.ctx = self.memory.data.get("lead_info", {})
        self.prenom = self.ctx.get("prenom", "")
        self.ville = self.ctx.get("ville", "")
        self.typo = self.ctx.get("typo", "") or self.ctx.get("typologie", "") or ""
        self.stage = self.memory.get_stage()

    def _last_agent_message(self) -> str:
        msgs = self.memory.data.get("messages", [])
        for m in reversed(msgs):
            if m.get("role") == "assistant":
                return m.get("content", "").lower()
        return ""

    def _waiting_for(self) -> Optional[str]:
        last = self._last_agent_message()
        if not last:
            return None
        asks_ville = any(x in last for x in ["ville", "city", "localité", "localite", "secteur"])
        asks_typo = any(x in last for x in ["type", "typologie", "t2", "t3", "pièces", "pieces", "logement", "appartement"])
        asks_criteres = any(x in last for x in ["critères", "criteres", "préciser", "preciser", "indiquer"])
        if asks_criteres or (asks_ville and asks_typo):
            return "ville_et_typo"
        if asks_ville:
            return "ville"
        if asks_typo:
            return "typo"
        if any(x in last for x in ["toujours en recherche", "en recherche", "intéressé", "interesse", "disponible"]):
            return "oui_non"
        return None

    def send_opening_message(self) -> str:
        prenom = self.prenom or ""
        ville = self.ville or "votre ville"
        typo = self.typo or "logement"
        dernier_contact = self.ctx.get("date_dernier_contact", "") or "récemment"
        msg = f"Bonjour {prenom},\n\n"
        msg += "C'est Daniel de Vianova 👋\n\n"
        msg += f"Nous avions échangé ensemble le {dernier_contact} au sujet de votre recherche — "
        msg += "je voulais vous partager mon numéro professionnel et en profiter pour faire le point avec vous.\n\n"
        msg += f"Êtes-vous toujours en recherche d'un {typo} sur {ville} ?"
        return msg

    def _dedup_response(self, r1: str, r2: str) -> Tuple[str, str]:
        """Ne jamais envoyer exactement la même réponse que la précédente."""
        last = self.memory.data.get("lead_info", {}).get("_last_response", "")
        full = (r1 + " " + r2).strip()
        if full and full == last:
            logger.warning(f"[dedup] Réponse identique bloquée stage={self.stage!r}")
            return "", ""
        return r1, r2

    # ═══════════════════════════════════════════════════════════════════════════
    # DÉDUCTION D'INTENTION — intercepte avant la machine à états
    # ═══════════════════════════════════════════════════════════════════════════

    _TODAY_TRIGGERS = [
        "aujourd'hui", "ce soir", "ce matin", "cet après-midi", "maintenant",
        "là maintenant", "tout de suite", "dès aujourd'hui", "dans la journée",
        "aujourd hui", "auj ", "dispo aujourd", "dispo ce soir", "dispo ce matin",
        "libre aujourd", "libre ce soir", "vous êtes dispo", "vous êtes disponible",
        "disponible aujourd",
    ]
    _CONTACT_TRIGGERS = [
        "numéro direct", "numéro de téléphone", "votre numéro", "appeler directement",
        "coordonnées", "contact direct", "joindre directement",
    ]
    _PRESENTIEL_TRIGGERS = [
        "présentiel", "en personne", "face à face", "vous rencontrer",
        "se voir", "se rencontrer", "agence", "bureau",
    ]
    _MEET_PROBLEM_TRIGGERS = [
        "lien marche pas", "lien ne marche", "lien cassé", "meet marche pas",
        "visio marche pas", "lien invalide", "lien expiré", "lien ne fonctionne",
        "problème avec le lien", "lien zoom", "impossible d'ouvrir",
    ]
    # Stages où OUI/NON sont gérés explicitement — ne pas interférer
    _STRONG_OUI_NON_STAGES = {"rdv_propose", "confirme_creneau", "attente_email",
                               "attente_trouve", "rdv_confirme"}
    _OUI_NON_WORDS = {"oui", "non", "ok", "yes", "no", "d'accord", "parfait", "super"}

    def _deduce_intent(self, txt: str) -> dict:
        """
        Analyse le message AVANT la machine à états.
        Retourne {"action": str, "params": dict, "confidence": float}
        confidence >= 0.5 → l'action est exécutée, la machine à états est court-circuitée.
        """
        stage = self.stage

        # Garde-fou 1 : stages qui gèrent OUI/NON eux-mêmes → ne jamais interférer
        if stage in self._STRONG_OUI_NON_STAGES:
            has_oui_non = bool(set(txt.split()) & self._OUI_NON_WORDS)
            if has_oui_non:
                return {"action": "CONTINUE_FLOW", "params": {}, "confidence": 0.0}

        # ── CHECK_CALENDAR_TODAY ─────────────────────────────────────────────
        if any(t in txt for t in self._TODAY_TRIGGERS):
            # Garde-fou 2 : en attente_creneau, si un slot d'aujourd'hui est déjà proposé
            # → le prospect sélectionne ce créneau, pas besoin de re-chercher
            if stage == "attente_creneau":
                lead_info = self.memory.data.get("lead_info", {})
                creneaux = lead_info.get("creneaux_proposes", [])
                active = creneaux[-3:] if len(creneaux) >= 3 else creneaux
                today_day = datetime.now().strftime("%d")
                today_short = datetime.now().strftime("%-d")  # sans zéro
                today_in_proposed = any(
                    today_day in s or today_short in s
                    for s in active
                )
                if today_in_proposed:
                    return {"action": "CONTINUE_FLOW", "params": {}, "confidence": 0.0}
            return {"action": "CHECK_CALENDAR_TODAY", "params": {}, "confidence": 0.85}

        # ── CONTACT_DIRECT ───────────────────────────────────────────────────
        if any(t in txt for t in self._CONTACT_TRIGGERS):
            return {"action": "FREE_RESPONSE", "params": {"key": "contact_direct"}, "confidence": 0.80}

        # ── PRÉSENTIEL ───────────────────────────────────────────────────────
        if any(t in txt for t in self._PRESENTIEL_TRIGGERS):
            # Ne pas intercepter si "agence" est mentionné dans un stage de collecte info
            # (peut être une "agence immobilière" que le prospect cherche)
            if stage in ("waiting_info", "nouveaux_criteres"):
                return {"action": "CONTINUE_FLOW", "params": {}, "confidence": 0.0}
            return {"action": "FREE_RESPONSE", "params": {"key": "presentiel"}, "confidence": 0.75}

        # ── LIEN MEET CASSÉ ──────────────────────────────────────────────────
        if any(t in txt for t in self._MEET_PROBLEM_TRIGGERS):
            return {"action": "FREE_RESPONSE", "params": {"key": "lien_meet_ko"}, "confidence": 0.90}

        return {"action": "CONTINUE_FLOW", "params": {}, "confidence": 0.0}

    def _handle_deduced_intent(self, action: str, params: dict) -> Tuple[str, str]:
        """Exécute l'action déduite et retourne (reply1, reply2)."""
        prenom_part = f" {self.prenom}" if self.prenom else ""
        lead_info = self.memory.data.get("lead_info", {})
        creneaux_proposes = lead_info.get("creneaux_proposes", [])

        if action == "CHECK_CALENDAR_TODAY":
            _FR_DAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
            today_day = _FR_DAYS[datetime.now().weekday()]
            logger.info(f"[deduce] CHECK_CALENDAR_TODAY pour {today_day}")
            today_slots = get_slots_for_day(today_day, exclude=creneaux_proposes, count=3)
            if today_slots:
                self.memory.update_lead_info(creneaux_proposes=creneaux_proposes + today_slots)
                self.memory.set_stage("attente_creneau")
                self.memory.save()
                slots_str = "\n".join(f"• {s}" for s in today_slots)
                r = (f"Bonne nouvelle{prenom_part} ! J'ai encore des disponibilités aujourd'hui :\n"
                     f"{slots_str}\n\nLequel vous conviendrait ?")
            else:
                # Aucun créneau aujourd'hui → prochains disponibles
                next_slots = get_real_slots(exclude=creneaux_proposes, count=3)
                if next_slots:
                    self.memory.update_lead_info(creneaux_proposes=creneaux_proposes + next_slots)
                    self.memory.set_stage("attente_creneau")
                    self.memory.save()
                    slots_str = "\n".join(f"• {s}" for s in next_slots)
                    r = (f"Malheureusement je n'ai plus de disponibilité aujourd'hui{prenom_part}. "
                         f"Voici mes prochains créneaux :\n{slots_str}\n\nLequel vous conviendrait ?")
                else:
                    r = (f"Je n'ai malheureusement pas de disponibilité aujourd'hui{prenom_part}. "
                         f"Je vous recontacte dès qu'un créneau se libère !")
            store_response(self.memory, r)
            return r, ""

        if action == "FREE_RESPONSE":
            key = params.get("key", "")
            recovery = context_recovery(self.stage, self.memory)

            if key == "contact_direct":
                r = (_sc_get("contact_direct", 0) or
                     "Bien sûr ! Vous pouvez aussi joindre l'équipe Vianova directement. "
                     "Mais je suis là pour répondre à toutes vos questions ici aussi !")

            elif key == "presentiel":
                ville_part = f" à {self.ville}" if self.ville else ""
                r = (f"Bien sûr{prenom_part}, un rendez-vous en présentiel c'est toujours possible ! "
                     f"Nous avons des conseillers{ville_part} qui peuvent vous accueillir. "
                     f"On peut prévoir ça en même temps que votre échange de présentation si vous préférez.")

            elif key == "lien_meet_ko":
                slot = lead_info.get("creneau_en_attente", "")
                if slot:
                    r = (f"Je suis désolé pour ce problème technique{prenom_part} ! "
                         f"Pas d'inquiétude — pour votre RDV du {slot}, je vous appellerai directement "
                         f"sur ce numéro. Pas besoin de lien. 😊")
                else:
                    r = (f"Je suis désolé pour ce problème{prenom_part} ! "
                         f"Je vous appellerai directement sur ce numéro pour notre échange. 😊")
            else:
                r = (f"Bien sûr{prenom_part} ! "
                     f"N'hésitez pas si vous avez d'autres questions.")

            # Toujours reprendre le fil avec la question prioritaire du stage
            full = r + (f"\n\n{recovery}" if recovery else "")
            store_response(self.memory, full)
            return full, ""

        # CONTINUE_FLOW — ne devrait pas arriver ici (confidence < 0.5)
        return "", ""

    # ═══════════════════════════════════════════════════════════════════════════

    def _confirme_rdv_direct(self, slot: str) -> Tuple[str, str]:
        """Confirme directement un RDV sans demander 'C'est bien ça ?'"""
        email = self.memory.data.get("lead_info", {}).get("email", "")
        prenom = self.prenom or ""
        meet_link = None
        if slot:
            try:
                meet_link = create_calendar_event(email or None, self.phone, slot, prenom)
            except Exception:
                meet_link = None
        self.memory.update_lead_info(creneau_en_attente=slot)
        self.memory.set_stage("rdv_confirme")
        self.memory.save()
        # Lien Meet jamais envoyé au prospect (l'événement est créé dans l'agenda Daniel uniquement)
        return ((_sc_get('rdv_confirme_sans_lien', 0) or "C'est parfait{p} ! Votre RDV est confirmé pour le {creneau}. Je vous appelle à l'heure convenue. À très bientôt ! 😊")
                .replace('{p}', ' ' + prenom if prenom else '').replace("C'est parfait  !", "C'est parfait !")
                .replace('{creneau}', slot).replace('{prenom}', prenom)), ""

    def process_message(self, user_msg: str, msg_id: str = None) -> Tuple[str, str]:
        if msg_id and self.memory.is_duplicate(msg_id):
            return "", ""

        self.stage = self.memory.get_stage()
        self.memory.add_message("user", user_msg, msg_id)
        txt = user_msg.lower().strip()
        original = user_msg.strip()

        # ── LOOP BREAK : même réponse envoyée 2x sans avancement ─────────────
        if detect_loop(self.memory):
            logger.warning(f"[loop] Boucle détectée stage={self.stage!r} — forçage hors-contexte")
            recovery = context_recovery(self.stage, self.memory)
            r = recovery or "Je suis là si vous avez des questions. Comment puis-je vous aider ?"
            store_response(self.memory, r)
            return r, ""

        # ── "VOUS ÊTES QUI ?" : ré-identification naturelle ───────────────────
        _QUI_PATTERNS = [
            r"\bvous\s+[eê]tes\s+qui\b",
            r"\bc['']est\s+qui\b",
            r"\bqui\s+[eê]tes[\s-]vous\b",
            r"\bqui\s+es[\s-]tu\b",
            r"\bde\s+(qui|la\s+part\s+de\s+qui)\b",
            r"\bje\s+(vous|te)\s+connais\s+pas\b",
            r"\bje\s+ne\s+(vous|te)\s+connais\s+pas\b",
            r"\bvous\s+[eê]tes\s+de\s+qui\b",
            r"\bc['']est\s+quoi\s+(vianova|ce\s+(message|num[eé]ro))\b",
        ]
        import re as _re2
        if any(_re2.search(p, txt, _re2.IGNORECASE) for p in _QUI_PATTERNS):
            prenom_part = f" {self.prenom}" if self.prenom else ""
            if self.ville and self.typo:
                r = f"C'est Daniel de Vianova{prenom_part}, on avait échangé pour votre recherche d'un {self.typo} à {self.ville} 👋 Vous êtes toujours sur ce projet ?"
            elif self.ville:
                r = f"C'est Daniel de Vianova{prenom_part}, on avait échangé pour votre projet immobilier à {self.ville} 👋 Toujours en recherche ?"
            elif self.typo:
                r = f"C'est Daniel de Vianova{prenom_part}, on avait échangé pour votre projet d'un {self.typo} 👋 Toujours en recherche ?"
            else:
                r = f"C'est Daniel de Vianova{prenom_part} 👋 On avait échangé pour votre projet immobilier. Toujours en recherche ?"
            store_response(self.memory, r)
            return r, ""

        # ── HORS-CONTEXTE : détection avant tout routing ─────────────────────
        faq_key = detect_off_context(txt, self.stage)
        if faq_key:
            faq_resp = off_context_response(faq_key, txt, self.memory)
            recovery = context_recovery(self.stage, self.memory)
            # Stop = pas de reprise
            if faq_key in ("stop",):
                store_response(self.memory, faq_resp)
                self.memory.set_stage("clos")
                self.memory.save()
                return faq_resp, ""
            full = faq_resp + ("\n\n" + recovery if recovery else "")
            store_response(self.memory, full)
            return full, ""

        # ── BONJOUR ──────────────────────────────────────────────────────────
        if txt in ["bonjour", "salut", "hey", "hello", "coucou"]:
            return _sc_get('bonjour', 0) or "Bonjour ! 👋 C'est Daniel de Vianova. Je suis ravi de vous accueillir.", ""

        # ── RETOURNEMENT : prospect revient après avoir clôturé ──────────────
        _REVERSAL_TRIGGERS = [
            "finalement", "en fait", "j'ai changé d'avis", "je change d'avis",
            "je suis disponible", "je suis libre", "ça m'intéresse",
            "j'aimerais quand même", "je veux quand même", "je suis intéressé",
            "reconsidéré", "pourquoi pas finalement", "bonne idée", "je veux bien",
        ]
        if self.stage == "clos" and any(tr in txt for tr in _REVERSAL_TRIGGERS):
            logger.info("[reversal] Réouverture depuis clos")
            prenom_part = f" {self.prenom}" if self.prenom else ""
            if self.ville and self.typo:
                slots = get_real_slots()
                if slots:
                    self.memory.update_lead_info(creneaux_proposes=slots[:3])
                    self.memory.set_stage("attente_creneau")
                    slots_str = "\n".join(f"• {s}" for s in slots[:3])
                    r = f"Pas de souci{prenom_part} ! Je suis ravi de vous retrouver. Voici mes disponibilités :\n{slots_str}\n\nLequel vous conviendrait ?"
                else:
                    self.memory.set_stage("rdv_propose")
                    r = f"Pas de souci{prenom_part} ! Je suis ravi. Seriez-vous disponible pour un échange téléphonique cette semaine ?"
            else:
                self.memory.set_stage("waiting_info")
                r = f"Pas de souci{prenom_part} ! Je reste à votre disposition. Sur quelle ville et quel type de bien portait votre recherche ?"
            self.memory.save()
            store_response(self.memory, r)
            return r, ""

        # ── DÉDUCTION D'INTENTION ─────────────────────────────────────────────
        _intent = self._deduce_intent(txt)
        if _intent["confidence"] >= 0.5:
            logger.info(f"[deduce] action={_intent['action']!r} conf={_intent['confidence']:.2f} stage={self.stage!r}")
            return self._handle_deduced_intent(_intent["action"], _intent["params"])

        # ── RDV_PROPOSE ──────────────────────────────────────────────────────
        if self.stage == "rdv_propose":
            rdv_result = self._classify_intent(original, "RDV_PROPOSE")
            rdv_intent = rdv_result.get("intent", "UNKNOWN")
            if rdv_intent == "ACCEPTE_RDV":
                self.memory.set_stage("attente_email")
                self.memory.save()
                prenom = self.prenom or ""
                tpl = _sc_get('rdv_accepte_email', 0) or "Parfait {prenom} ! Pour confirmer le rendez-vous, pourriez-vous me communiquer votre adresse email ?"
                return tpl.replace('{prenom}', (' ' + prenom) if prenom else '').replace('Parfait  !', 'Parfait !'), ""
            if rdv_intent == "REFUSE_RDV":
                self.memory.set_stage("clos")
                self.memory.save()
                return _sc_get('rdv_refuse', 0) or "Je comprends tout à fait. N'hésitez pas à revenir vers moi. Belle journée !", ""
            if rdv_intent == "HORS_CONTEXTE":
                llm_r, _ = self._llm_fallback(txt, original)
                if llm_r and llm_r != "__PAUSE__":
                    recovery = context_recovery(self.stage, self.memory) or ""
                    return llm_r + ("\n\n" + recovery if recovery else ""), ""
            # UNKNOWN → laisser continuer le flow (fallback générique)

        # ── ATTENTE_EMAIL ─────────────────────────────────────────────────────
        if self.stage == "attente_email":
            email = _detect_email(original)
            if email:
                self.memory.update_lead_info(email=email)
                creneaux_proposes = self.memory.data.get("lead_info", {}).get("creneaux_proposes", [])
                slots = get_real_slots(exclude=creneaux_proposes, count=3)
                self.memory.update_lead_info(creneaux_proposes=creneaux_proposes + slots)
                self.memory.set_stage("attente_creneau")
                self.memory.save()
                slots_str = "\n".join(f"• {s}" for s in slots)
                prenom = self.prenom or ""
                return (f"Merci{' ' + prenom if prenom else ''} ! "
                        f"Voici mes disponibilités pour notre échange :\n{slots_str}\n\n"
                        f"Lequel vous conviendrait le mieux ?"), ""
            if any(x in txt for x in ["non", "pas email", "sans email", "pas d'email",
                                        "téléphone", "telephone", "appel", "direct"]):
                creneaux_proposes = self.memory.data.get("lead_info", {}).get("creneaux_proposes", [])
                slots = get_real_slots(exclude=creneaux_proposes, count=3)
                self.memory.update_lead_info(creneaux_proposes=creneaux_proposes + slots)
                self.memory.set_stage("attente_creneau")
                self.memory.save()
                slots_str = "\n".join(f"• {s}" for s in slots)
                return (f"Très bien, pas de souci ! Nous passerons directement par un appel téléphonique. "
                        f"Voici mes disponibilités :\n{slots_str}\n\nLequel vous conviendrait le mieux ?"), ""
            return "Pourriez-vous me communiquer votre adresse email pour confirmer le rendez-vous ?", ""

        # ── ATTENTE_CRENEAU ───────────────────────────────────────────────────
        if self.stage == "attente_creneau":
            creneaux_proposes = self.memory.data.get("lead_info", {}).get("creneaux_proposes", [])
            active_slots = creneaux_proposes[-3:] if len(creneaux_proposes) >= 3 else creneaux_proposes

            requested_day = _extract_requested_day(txt)
            is_non = any(x in txt for x in ["non", "aucun", "pas disponible", "ne convient pas",
                                              "pas possible", "impossible"])

            # 1. NON explicite (sans jour mentionné)
            if is_non and not requested_day:
                self.memory.set_stage("relance_creneau")
                self.memory.save()
                return _sc_get('relance_creneau', 0) or ("De votre côté, êtes-vous plutôt disponible en journée (entre 9h et 18h) "
                        "en début de semaine ou plutôt en fin de semaine ? "
                        "Et plutôt le matin ou l'après-midi ?"), ""

            # 2. PRIORITÉ : créneau précis détecté (ordinal, jour+heure, heure seule)
            #    → doit passer AVANT le check jour pour éviter "lundi à 10h" → re-propose tous les lundis
            chosen = _detect_slot_from_proposed(txt, active_slots)
            if chosen:
                return self._confirme_rdv_direct(chosen)

            # 3. Le prospect mentionne un jour (mais pas de créneau précis)
            if requested_day:
                slots_ce_jour = [s for s in active_slots if requested_day in s.lower()]
                if slots_ce_jour:
                    if len(slots_ce_jour) == 1:
                        return self._confirme_rdv_direct(slots_ce_jour[0])
                    else:
                        slots_str = "\n".join(f"• {s}" for s in slots_ce_jour)
                        return (f"{requested_day.capitalize()}, j'ai ces disponibilités :\n{slots_str}\n\n"
                                f"Laquelle vous convient ?"), ""
                else:
                    new_slots = get_slots_for_day(requested_day, exclude=creneaux_proposes, count=5)
                    if new_slots:
                        self.memory.update_lead_info(creneaux_proposes=creneaux_proposes + new_slots)
                        self.memory.save()
                        if len(new_slots) == 1:
                            return self._confirme_rdv_direct(new_slots[0])
                        else:
                            slots_str = "\n".join(f"• {s}" for s in new_slots)
                            return (f"{requested_day.capitalize()}, j'ai ces disponibilités :\n{slots_str}\n\n"
                                    f"Laquelle vous convient ?"), ""
                    else:
                        return (f"Je n'ai malheureusement pas de disponibilité {requested_day}. "
                                f"Souhaitez-vous un autre jour ?"), ""

            # 4. Réponse positive générique mais aucun créneau précis → rappeler les créneaux
            if any(x in txt for x in ["oui", "ok", "d'accord", "bien sûr", "super", "parfait"]):
                if not active_slots:
                    active_slots = get_real_slots(count=3)
                    self.memory.update_lead_info(creneaux_proposes=active_slots)
                    self.memory.save()
                slots_str = "\n".join(f"• {s}" for s in active_slots)
                return f"Lequel de ces créneaux vous convient le mieux ?\n{slots_str}", ""

            # 5. Ambiguous → LLM classifier pour distinguer INFIRME / MODIFIE / HORS_CONTEXTE
            creneau_result = self._classify_intent(original, "CONFIRMATION_CRENEAU")
            creneau_intent = creneau_result.get("intent", "UNKNOWN")
            extracted_c = creneau_result.get("extracted", {})
            if creneau_intent == "INFIRME":
                self.memory.set_stage("relance_creneau")
                self.memory.save()
                return _sc_get('relance_creneau', 0) or ("De votre côté, êtes-vous plutôt disponible en journée "
                    "en début de semaine ou plutôt en fin de semaine ? Plutôt le matin ou l'après-midi ?"), ""
            if creneau_intent == "MODIFIE":
                jour = extracted_c.get("jour_prefere") or ""
                if jour:
                    new_slots = get_slots_for_day(jour.lower(), exclude=creneaux_proposes, count=3)
                    if new_slots:
                        self.memory.update_lead_info(creneaux_proposes=creneaux_proposes + new_slots)
                        self.memory.save()
                        slots_str = "\n".join(f"• {s}" for s in new_slots)
                        return f"{jour.capitalize()}, voici mes disponibilités :\n{slots_str}\n\nLequel vous conviendrait ?", ""
                # Pas de jour précis → demander les préférences
                self.memory.set_stage("relance_creneau")
                self.memory.save()
                return "Quelles sont vos disponibilités en général ? (Matin, après-midi, début ou fin de semaine ?)", ""
            if creneau_intent == "HORS_CONTEXTE":
                llm_r, _ = self._llm_fallback(txt, original)
                if llm_r and llm_r != "__PAUSE__":
                    if not active_slots:
                        active_slots = get_real_slots(count=3)
                    slots_str = "\n".join(f"• {s}" for s in active_slots)
                    return llm_r + f"\n\nPour rappel, voici les créneaux disponibles :\n{slots_str}", ""
            # UNKNOWN / CONFIRME sans slot détecté → rappeler les créneaux
            if not active_slots:
                active_slots = get_real_slots(count=3)
                self.memory.update_lead_info(creneaux_proposes=active_slots)
                self.memory.save()
            slots_str = "\n".join(f"• {s}" for s in active_slots)
            return f"Parmi ces créneaux, lequel vous conviendrait ?\n{slots_str}", ""

        # ── CONFIRME_CRENEAU ──────────────────────────────────────────────────
        if self.stage == "confirme_creneau":
            slot_en_attente = self.memory.data.get("lead_info", {}).get("creneau_en_attente", "")
            is_oui = any(x in txt for x in ["oui", "yes", "ok", "c'est bon", "parfait", "exactement",
                                              "exact", "correct", "d'accord", "tout à fait", "nickel",
                                              "impeccable", "super", "bien", "oui c'est"])
            is_non = any(x in txt for x in ["non", "no", "pas", "autre", "changer", "différent",
                                              "autrement", "pas bon", "pas ce"])

            if is_oui:
                email = self.memory.data.get("lead_info", {}).get("email", "")
                prenom = self.prenom or ""
                meet_link = None
                if slot_en_attente:
                    try:
                        meet_link = create_calendar_event(email or None, self.phone, slot_en_attente, prenom)
                    except Exception:
                        meet_link = None
                self.memory.set_stage("rdv_confirme")
                self.memory.save()
                # Lien Meet jamais envoyé au prospect
                return ((_sc_get('rdv_confirme_sans_lien', 0) or "C'est parfait{p} ! Votre RDV est confirmé pour le {creneau}. Je vous appelle à l'heure convenue. À très bientôt ! 😊")
                        .replace('{p}', ' ' + prenom if prenom else '').replace('C\'est parfait  !', 'C\'est parfait !')
                        .replace('{creneau}', slot_en_attente).replace('{prenom}', prenom)), ""

            if is_non:
                creneaux_proposes = self.memory.data.get("lead_info", {}).get("creneaux_proposes", [])
                slots = get_real_slots(exclude=creneaux_proposes, count=3)
                self.memory.update_lead_info(creneaux_proposes=creneaux_proposes + slots, creneau_en_attente=None)
                self.memory.set_stage("attente_creneau")
                self.memory.save()
                slots_str = "\n".join(f"• {s}" for s in slots)
                return f"Pas de souci ! Voici d'autres créneaux disponibles :\n{slots_str}\n\nLequel vous convient ?", ""

            return f"Pour confirmer : le {slot_en_attente} vous convient bien ? (Oui/Non)", ""

        # ── RELANCE_CRENEAU ───────────────────────────────────────────────────
        if self.stage == "relance_creneau":
            creneaux_proposes = self.memory.data.get("lead_info", {}).get("creneaux_proposes", [])
            requested_day = _extract_requested_day(txt)
            if requested_day:
                slots = get_slots_for_day(requested_day, exclude=creneaux_proposes, count=5)
            else:
                slots = get_real_slots(exclude=creneaux_proposes, count=3)
            self.memory.update_lead_info(creneaux_proposes=creneaux_proposes + slots)
            self.memory.set_stage("attente_creneau")
            self.memory.save()
            slots_str = "\n".join(f"• {s}" for s in slots)
            return f"Voici des créneaux qui devraient vous convenir :\n{slots_str}\n\nLequel vous arrange ?", ""

        if self.stage == "rdv_confirme":
            # Réponse normale aux remerciements / clôtures
            if any(x in txt for x in ["merci", "parfait", "super", "ok", "bientôt",
                                        "à bientôt", "au revoir", "bye", "bonne journée",
                                        "bonne soirée", "nickel", "top", "d'accord"]):
                r = "À très bientôt ! 😊 N'hésitez pas si vous avez des questions d'ici là."
                store_response(self.memory, r)
                return r, ""
            # Pour tout autre message en rdv_confirme → réponse contextuelle
            lead = self.memory.data.get("lead_info", {})
            slot = lead.get("creneau_en_attente", "")
            r = f"Votre RDV est bien confirmé pour le {slot}. À très bientôt ! 😊" if slot else "Votre rendez-vous est bien confirmé. À très bientôt ! 😊"
            store_response(self.memory, r)
            return r, ""

        # ── NOUVEAUX_CRITERES : collecte progressive ville + type ─────────────
        if self.stage == "nouveaux_criteres":
            # Classifier l'intention pour distinguer critères donnés / pas de critères / hors-contexte
            nc_result = self._classify_intent(original, "NOUVEAUX_CRITERES")
            nc_intent = nc_result.get("intent", "UNKNOWN")
            nc_extracted = nc_result.get("extracted", {})
            logger.info(f"[classify_nc] intent={nc_intent!r} extracted={nc_extracted}")

            if nc_intent == "HORS_CONTEXTE":
                llm_resp, _ = self._llm_fallback(txt, original)
                if llm_resp and llm_resp != "__PAUSE__":
                    recovery = context_recovery(self.stage, self.memory) or ""
                    return llm_resp + ("\n\n" + recovery if recovery else ""), ""
                prenom_part = f" {self.prenom}" if self.prenom else ""
                return f"Pour vous trouver le bien idéal{prenom_part}, j'ai besoin de deux infos : dans quelle ville cherchez-vous, et quel type de bien vous intéresse (T2, T3...) ?", ""

            if nc_intent == "PAS_DE_CRITERES":
                # Rebond naturel : le prospect ne sait pas encore
                _REBONDS = [
                    ("sais pas", "Je comprends, on prend le temps ! Pour que je puisse vous montrer ce qu'on a, dites-moi juste dans quelle région vous cherchez en ce moment ?"),
                    ("aucune idée", "Pas de souci ! On démarre par le plus simple : vous avez une idée de la ville ou du secteur ?"),
                    ("réfléchi", "Bien sûr, prenez le temps ! Dites-moi juste la ville quand vous êtes prêt, je regarde ce qu'on a disponible."),
                    ("hésit", "Je comprends ! Pour commencer, dans quelle zone géographique cherchez-vous principalement ?"),
                    ("compliqué", "Pas de pression ! Juste pour orienter ma recherche, vous avez une idée de la ville ou du secteur ?"),
                ]
                for kw, resp in _REBONDS:
                    if kw in txt:
                        store_response(self.memory, resp)
                        return resp, ""
                prenom_part = f" {self.prenom}" if self.prenom else ""
                r = f"Pas de problème{prenom_part} ! Prenez le temps. Quand vous avez une idée, dites-moi juste la ville et le type de bien — je regarde ce qu'on a de disponible."
                store_response(self.memory, r)
                return r, ""

            # DONNE_CRITERES ou UNKNOWN → extraire ville/typo et accumuler progressivement
            lead_info = self.memory.data.get("lead_info", {})
            nc_ville = lead_info.get("_nc_ville", "") or ""
            nc_type  = lead_info.get("_nc_type",  "") or ""

            # Utiliser les champs extraits par le classifier en priorité, puis le parser regex
            ville_det = nc_extracted.get("ville") or None
            typo_det  = nc_extracted.get("type_bien") or None
            if not ville_det or not typo_det:
                ville_regex, typo_regex = _parse_ville_typo_from_lines(original)
                if not ville_det:
                    ville_det = ville_regex
                if not typo_det:
                    typo_det = typo_regex

            if ville_det:
                nc_ville = ville_det
                self.memory.update_lead_info(_nc_ville=nc_ville)
            if typo_det:
                nc_type = _normalize_typo(typo_det) or typo_det
                self.memory.update_lead_info(_nc_type=nc_type)

            if nc_ville and nc_type:
                # Les deux connus → on consolide et on part en branche OUI
                self.ville = nc_ville
                self.typo  = nc_type
                self.memory.update_lead_info(ville=nc_ville, typo=nc_type, _nc_ville=None, _nc_type=None)
                self.memory.set_stage("waiting_info")
                self.memory.save()
                return self._branche_oui()

            # Réponse naturelle selon ce qui manque
            if nc_ville and not nc_type:
                r = f"{nc_ville}, c'est une belle zone, il y a de belles opportunités ! Et côté superficie, vous visez quel type de bien — un T2, T3, T4 ?"
                store_response(self.memory, r)
                return r, ""

            if nc_type and not nc_ville:
                r = f"Parfait pour un {nc_type} ! Et dans quelle ville ou secteur géographique vous positionnez-vous ?"
                store_response(self.memory, r)
                return r, ""

            # Rien détecté malgré DONNE_CRITERES — reposer la question
            prenom_part = f" {self.prenom}" if self.prenom else ""
            r = f"Pour vous trouver le bien idéal{prenom_part}, j'ai besoin de deux infos : dans quelle ville cherchez-vous, et quel type de bien vous intéresse (T2, T3...) ?"
            store_response(self.memory, r)
            return r, ""

        # ── LECTURE DU CONTEXTE ───────────────────────────────────────────────
        waiting = self._waiting_for()

        # ── CLASSIFIER LLM : réponse initiale à la question "toujours en recherche ?" ──
        if waiting == "oui_non":
            result = self._classify_intent(original, "ATTENTE_REPONSE_INITIALE")
            intent = result.get("intent", "UNKNOWN")
            extracted = result.get("extracted", {})
            logger.info(f"[classify_initial] intent={intent!r} extracted={extracted}")

            if intent == "OUI_MEME_CRITERES":
                if self.ville and self.typo:
                    return self._branche_oui()
                self.memory.set_stage("waiting_info")
                self.memory.save()
                return "Super ! Pouvez-vous me confirmer la ville et le type de bien recherché ? (ex: Saint-Denis, T3)", ""

            elif intent == "OUI_NOUVEAUX_CRITERES":
                ville_new = extracted.get("ville")
                typo_new = extracted.get("type_bien")
                if ville_new:
                    self.ville = ville_new
                    self.memory.update_lead_info(ville=ville_new)
                if typo_new:
                    typo_norm = _normalize_typo(typo_new) or typo_new
                    self.typo = typo_norm
                    self.memory.update_lead_info(typo=typo_norm)
                if self.ville and self.typo:
                    return self._branche_oui()
                self.memory.set_stage("waiting_info")
                self.memory.save()
                if not self.ville:
                    return "Pas de problème ! Sur quelle ville cherchez-vous maintenant ?", ""
                return "Pas de problème ! Et quel type de bien ? (T2, T3, T4...)", ""

            elif intent == "NON_TROUVE":
                self.memory.set_stage("clos")
                self.memory.save()
                prenom_part = f" {self.prenom}" if self.prenom else ""
                return f"Félicitations{prenom_part} ! Je suis vraiment ravi pour vous. N'hésitez pas si besoin à l'avenir. Belle suite ! 😊", ""

            elif intent == "NON_CHERCHE_PLUS":
                # Pas fermer direct : on vérifie s'ils ont trouvé ou abandonné
                self.memory.set_stage("attente_trouve")
                self.memory.save()
                return "Je comprends. Avez-vous trouvé votre bonheur de votre côté ?", ""

            else:
                # HORS_CONTEXTE / UNKNOWN → réponse libre LLM + relance vers RDV
                llm_resp, _ = self._llm_fallback(txt, original)
                if llm_resp and llm_resp != "__PAUSE__":
                    recovery = context_recovery(self.stage, self.memory) or ""
                    return llm_resp + ("\n\n" + recovery if recovery else ""), ""
                return "Je ne suis pas sûr de comprendre. Êtes-vous toujours en recherche immobilière ?", ""

        if waiting in ("ville", "ville_et_typo", "typo"):
            ville_detected, typo_detected = _parse_ville_typo_from_lines(original)
            logger.info(f"[parse] ville={ville_detected!r} typo={typo_detected!r} (msg={original!r})")

            if ville_detected and typo_detected:
                self.ville = ville_detected
                self.typo = typo_detected
                self.memory.update_lead_info(ville=ville_detected, typo=typo_detected)
            elif ville_detected:
                self.ville = ville_detected
                self.memory.update_lead_info(ville=ville_detected)
                # Ne pas utiliser la typo stale — demander explicitement
                if not self.typo or waiting == "ville_et_typo":
                    return "Parfait ! Et quel type de bien recherchez-vous ? (T2, T3, T4...)", ""
            elif typo_detected:
                self.typo = typo_detected
                self.memory.update_lead_info(typo=typo_detected)

            if self.ville and self.typo:
                return self._branche_oui()
            if self.ville and not self.typo:
                return "Parfait ! Et quel type de bien recherchez-vous ? (T2, T3, T4...)", ""
            if self.typo and not self.ville:
                return "Très bien ! Et sur quelle ville recherchez-vous ?", ""
            return "Pouvez-vous me préciser la ville et le type de bien recherché ? (ex: Saint-Denis, T3)", ""

        # ── ATTENTE_TROUVE ────────────────────────────────────────────────────
        # DOIT être avant le catch-all OUI : "Avez-vous trouvé ?" → "Oui" ≠ intérêt stock
        if self.stage == "attente_trouve":
            bonheur_result = self._classify_intent(original, "ATTENTE_BONHEUR")
            bonheur_intent = bonheur_result.get("intent", "UNKNOWN")
            if bonheur_intent == "TROUVE":
                self.memory.set_stage("clos")
                self.memory.save()
                prenom_part = f" {self.prenom}" if self.prenom else ""
                return f"Félicitations{prenom_part} ! Je suis ravi pour vous. N'hésitez pas si besoin à l'avenir. 😊", ""
            if bonheur_intent == "PAS_TROUVE":
                self.ville = ""
                self.typo = ""
                prenom_part = f" {self.prenom}" if self.prenom else ""
                self.memory.update_lead_info(ville="", typo="", _nc_ville="", _nc_type="")
                self.memory.set_stage("nouveaux_criteres")
                self.memory.save()
                r = f"D'accord{prenom_part} ! Et si on repartait sur de nouvelles bases — vous avez des critères différents en tête ? Une ville, un type de bien ?"
                store_response(self.memory, r)
                return r, ""
            if bonheur_intent == "HORS_CONTEXTE":
                llm_r, _ = self._llm_fallback(txt, original)
                if llm_r and llm_r != "__PAUSE__":
                    return llm_r + "\n\nAvez-vous trouvé votre bonheur de votre côté ?", ""
            # UNKNOWN → reposer la question
            return "Je comprends. Avez-vous trouvé votre bonheur de votre côté ?", ""

        # ── BRANCHE OUI ──────────────────────────────────────────────────────
        # Ne s'active que si aucun stage spécifique n'a été géré avant
        if any(x in txt for x in ["oui", "yes", "ok", "carrément", "bien sûr", "volontiers", "avec plaisir",
                                    "toujours", "effectivement", "exactement", "tout à fait"]):
            # Si on attendait uniquement un OUI/NON (ex: "Êtes-vous toujours en recherche ?")
            # → ne JAMAIS tenter d'extraire une ville/typo du message de confirmation
            # → "Merci pour ce retour. Oui toujours." doit rester OUI, pas "ville=Retour"
            if self._waiting_for() == "oui_non":
                logger.info(f"[branche_oui_parse] waiting=oui_non → skip extract ville/typo (msg={original!r})")
                if self.ville and self.typo:
                    return self._branche_oui()
                self.memory.set_stage("waiting_info")
                self.memory.save()
                return "Super ! Pouvez-vous me confirmer la ville et le type de bien recherché ? (ex: Saint-Denis, T3)", ""

            # Sinon : parser sur le message NETTOYÉ des formules de politesse
            # Ex: "Oui à Lille un T4" → ville=Lille, typo=T4
            cleaned_original = _clean_polite(original)
            ville_in_msg, typo_in_msg = _parse_ville_typo_from_lines(cleaned_original)
            logger.info(f"[branche_oui_parse] ville_in_msg={ville_in_msg!r} typo_in_msg={typo_in_msg!r} (cleaned='{cleaned_original[:60]}')")
            if ville_in_msg:
                self.ville = ville_in_msg
                self.memory.update_lead_info(ville=ville_in_msg)
            if typo_in_msg:
                self.typo = typo_in_msg
                self.memory.update_lead_info(typo=typo_in_msg)

            if not self.ville or not self.typo:
                self.memory.set_stage("waiting_info")
                self.memory.save()
                return "Super ! Pouvez-vous me confirmer la ville et le type de bien recherché ? (ex: Saint-Denis, T3)", ""
            return self._branche_oui()

        # ── BRANCHE NON ──────────────────────────────────────────────────────
        _NON_EXPLICIT = ["non", "pas besoin", "plus intéressé", "annulé", "pas intéressé",
                         "pas pour moi", "pas concerné", "pas de projet", "merci non", "non merci"]
        _NON_IMPLICIT = [
            # Ont trouvé / sont partis sur autre chose
            r"parti[e]? sur", r"on est parti", r"sommes parti", r"on a opté",
            r"on a choisi", r"avons choisi", r"avons (acheté|signé|trouvé)",
            r"on a (acheté|signé|trouvé|finalisé)", r"j.?ai (acheté|signé)",
            r"(compromis|acte|vente) (signé|finalisé)",
            # Plus en recherche
            r"plus en recherche", r"plus à la recherche", r"arrêté (de chercher|les recherches)",
            r"plus d.?actualité", r"n.?est plus d.?actualité", r"projet (tombé|abandonné|suspendu|annulé)",
            r"laissé tomber", r"on a laissé", r"plus le moment", r"pas le bon moment",
            # Budget / contexte différent
            r"pas dans (notre|mon) budget", r"plus dans (notre|mon) budget",
            r"budget ne (nous|me) permet", r"hors (de notre|de mon) budget",
            # Trouvé quelque chose (sans "pas encore")
            r"on a trouvé ce (qu|que)", r"trouvé notre bonheur", r"trouvé ce qu",
        ]
        import re as _re
        _is_non = any(x in txt for x in _NON_EXPLICIT)
        if not _is_non:
            for pat in _NON_IMPLICIT:
                if _re.search(pat, txt, _re.IGNORECASE):
                    _is_non = True
                    break
        if _is_non:
            return self._branche_non()

        # ── FALLBACK ─────────────────────────────────────────────────────────
        # Nettoyer les formules de politesse avant extraction pour éviter "Retour" → ville
        _orig_cleaned = _clean_polite(original)
        ville_detected, typo_detected = _parse_ville_typo_from_lines(_orig_cleaned)
        logger.info(f"[fallback parse] ville={ville_detected!r} typo={typo_detected!r} (cleaned='{_orig_cleaned[:60]}')")
        if ville_detected or typo_detected:
            if ville_detected:
                self.ville = ville_detected
                self.memory.update_lead_info(ville=ville_detected)
            if typo_detected:
                self.typo = typo_detected
                self.memory.update_lead_info(typo=typo_detected)
            if self.ville and self.typo:
                # Les deux sont connus (l'un ou l'autre vient d'être détecté) → chercher le stock
                # Ex: "PARIS ??" → ville=Paris détecté, typo=T1 déjà en mémoire → _branche_oui
                return self._branche_oui()
            if self.ville and not self.typo:
                return "Parfait ! Et quel type de bien recherchez-vous ? (T2, T3, T4...)", ""
            if self.typo and not self.ville:
                return "Très bien ! Et sur quelle ville recherchez-vous ?", ""

        # ── DÉTECTION IA ─────────────────────────────────────────────────────
        # Si le prospect détecte/questionne sur le fait que c'est une IA → pause immédiate, sans réponse
        _IA_PATTERNS = [
            r"t[u']?\s*es\s+(une?\s+)?(ia|intelligence artificielle|robot|bot|chatbot|automate|programme|logiciel|machine)",
            r"vous\s+[eê]tes\s+(une?\s+)?(ia|intelligence artificielle|robot|bot|chatbot|automate|programme|logiciel|machine)",
            r"c['']est\s+(une?\s+)?(ia|intelligence artificielle|robot|bot|chatbot|automate|programme|logiciel|machine)",
            r"c['']est\s+pas\s+(un\s+)?humain",
            r"je\s+parle\s+(à\s+)?(une?\s+)?(ia|robot|bot|machine|programme)",
            r"(ia|bot|robot|automate|chatbot)\s+ou\s+(humain|personne|quelqu[u']un)",
            r"(humain|personne|quelqu[u']un)\s+ou\s+(ia|bot|robot|automate|chatbot)",
            r"(vraiment|vrai)\s+(un\s+)?(humain|conseiller|personne)",
            r"t[u']?\s*es\s+(vraiment\s+)?(humain|une\s+vraie\s+personne|réel)",
            r"je\s+suis\s+sûr\s+(que\s+c['']est|que\s+t[u']?\s+es)\s+(une?\s+)?(ia|bot|robot)",
            r"c['']est\s+(clairement\s+)?une?\s+(ia|bot|robot)",
            r"détecté\s+(une?\s+)?(ia|bot|robot)",
        ]
        for _ia_pat in _IA_PATTERNS:
            if _re.search(_ia_pat, txt, _re.IGNORECASE):
                logger.info(f"[IA détectée] Pause automatique pour {self.phone} — message: {original!r}")
                return "__PAUSE__", ""

        # Fallback : le bot ne comprend pas → appel LLM (Claude Haiku) pour gérer
        logger.warning(f"[fallback→llm] Message non reconnu stage={self.stage!r} — appel LLM pour {self.phone}")
        return self._llm_fallback(txt, original)


    _STAGE_CONFIG = {
        "ATTENTE_REPONSE_INITIALE": {
            "intents": {
                "OUI_MEME_CRITERES":    "toujours en recherche, mêmes critères (ex: 'oui', 'toujours', 'c'est ça', 'exactement')",
                "OUI_NOUVEAUX_CRITERES":"en recherche MAIS avec critères différents — ATTENTION : 'non mais [ville/type]' ou 'pas [ville] mais [ville2]' est OUI_NOUVEAUX_CRITERES, pas NON (ex: 'plutôt à Paris', 'non mais je cherche à Lyon', 'pas un T1 mais un T3', 'j'ai changé de ville')",
                "NON_TROUVE":           "a trouvé un bien et ne cherche plus (ex: 'j'ai acheté', 'c'est bon j'ai trouvé', 'on a signé', 'c'est réglé')",
                "NON_CHERCHE_PLUS":     "a arrêté de chercher sans avoir trouvé (ex: 'j'ai abandonné', 'c'est plus d'actualité', 'on a laissé tomber')",
                "HORS_CONTEXTE":        "message sans rapport avec la recherche immobilière",
            },
            "extracted": '"ville": "<ville si mentionnée, sinon null>", "type_bien": "<T2/T3/etc si mentionné, sinon null>"',
        },
        "ATTENTE_BONHEUR": {
            "intents": {
                "TROUVE":       "a trouvé un bien / a signé (ex: 'oui j'ai trouvé', 'on a signé', 'c'est réglé')",
                "PAS_TROUVE":   "n'a pas trouvé, toujours en galère (ex: 'non pas encore', 'rien trouvé', 'toujours en recherche')",
                "HORS_CONTEXTE":"message sans rapport",
            },
            "extracted": None,
        },
        "RDV_PROPOSE": {
            "intents": {
                "ACCEPTE_RDV":  "accepte le rendez-vous (ex: 'oui', 'ok', 'avec plaisir', 'ça me convient', 'pourquoi pas')",
                "REFUSE_RDV":   "refuse le rendez-vous (ex: 'non', 'pas le temps', 'merci non', 'pas pour moi')",
                "HORS_CONTEXTE":"question hors sujet, réponse ambiguë ou donne une nouvelle ville/critère",
            },
            "extracted": None,
        },
        "CONFIRMATION_CRENEAU": {
            "intents": {
                "CONFIRME":     "valide un créneau spécifique parmi ceux proposés",
                "INFIRME":      "aucun créneau ne convient, sans proposer d'alternative claire",
                "MODIFIE":      "veut un autre moment ou précise ses disponibilités (jour, heure, matin/soir)",
                "HORS_CONTEXTE":"message sans rapport avec le créneau",
            },
            "extracted": '"jour_prefere": "<jour si mentionné, sinon null>", "preference_horaire": "<matin/apres-midi/soir si mentionné, sinon null>"',
        },
        "NOUVEAUX_CRITERES": {
            "intents": {
                "DONNE_CRITERES":   "donne des critères clairs — ville et/ou type de bien (ex: 'je cherche à Lyon un T3')",
                "PAS_DE_CRITERES":  "répond vaguement sans critères exploitables (ex: 'je sais pas', 'pas encore décidé')",
                "HORS_CONTEXTE":    "message sans rapport",
            },
            "extracted": '"ville": "<ville si mentionnée, sinon null>", "type_bien": "<T2/T3/etc si mentionné, sinon null>"',
        },
    }

    def _classify_intent(self, message: str, etape: str) -> dict:
        """
        Classificateur LLM générique — gère ATTENTE_REPONSE_INITIALE, ATTENTE_BONHEUR,
        RDV_PROPOSE, CONFIRMATION_CRENEAU, NOUVEAUX_CRITERES.
        Retourne {"intent": str, "extracted": dict}
        """
        import os, requests as _req, json as _json
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            logger.warning(f"[classify_intent] Pas de ANTHROPIC_API_KEY (etape={etape})")
            return {"intent": "UNKNOWN", "extracted": {}}

        config = self._STAGE_CONFIG.get(etape)
        if not config:
            return {"intent": "UNKNOWN", "extracted": {}}

        intents_list = "\n".join(f'- "{k}" : {v}' for k, v in config["intents"].items())
        extracted_desc = config.get("extracted")
        extracted_fmt = (f',\n  "extracted": {{{extracted_desc}}}') if extracted_desc else ',\n  "extracted": {}'

        msgs = self.memory.data.get("messages", [])[-6:]
        history = "\n".join(f"{m['role'].upper()}: {m.get('content','')[:200]}" for m in msgs[:-1])

        # Contexte session courant pour aider le classifier à interpréter les "non"
        session_ctx = ""
        if self.ville or self.typo:
            parts = []
            if self.ville:
                parts.append(f"ville actuelle={self.ville!r}")
            if self.typo:
                parts.append(f"type_bien actuel={self.typo!r}")
            session_ctx = f"\nContexte prospect : {', '.join(parts)} (le 'non' peut référer à ces critères, pas à l'abandon de recherche)"

        prompt = f"""Tu es un classificateur d'intention pour un agent immobilier WhatsApp.

Étape actuelle : {etape}{session_ctx}
Historique récent :
{history}

Message du prospect : "{message}"

Intents possibles :
{intents_list}

RÈGLE IMPORTANTE : Si le prospect dit "non mais [ville/critère]", "pas [ville] mais [ville2]", ou tout message qui commence par une négation MAIS donne de nouveaux critères, c'est OUI_NOUVEAUX_CRITERES (correction de critères), PAS NON_CHERCHE_PLUS.

Réponds UNIQUEMENT en JSON valide, sans texte autour :
{{
  "intent": "<intent>"{extracted_fmt}
}}"""

        try:
            resp = _req.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 150,
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=8,
            )
            content = resp.json()["content"][0]["text"].strip()
            if "```" in content:
                content = content.split("```")[1].strip()
                if content.startswith("json"):
                    content = content[4:].strip()
            result = _json.loads(content)
            logger.info(f"[classify_intent] etape={etape} intent={result.get('intent')} extracted={result.get('extracted', {})}")
            return result
        except Exception as e:
            logger.warning(f"[classify_intent] Erreur LLM etape={etape}: {e}")
            return {"intent": "UNKNOWN", "extracted": {}}

    def _llm_fallback(self, txt: str, original: str) -> tuple:
        """Appelle Claude Haiku quand le bot ne sait pas quoi faire.
        Retourne (response, "") ou ("__PAUSE__", "") si l'API échoue.
        """
        import os, requests as _req, json as _json
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            logger.warning("[llm_fallback] Pas de ANTHROPIC_API_KEY")
            return "__PAUSE__", ""

        # Récupérer l'historique récent de la conversation
        history = []
        try:
            msgs = self.memory.data.get("messages", [])[-6:]
            for m in msgs:
                role = "user" if m.get("role") == "user" else "assistant"
                history.append(f"{role}: {m.get('content','')[:200]}")
        except Exception:
            pass
        history_str = "\n".join(history) if history else "(debut de conversation)"

        prenom = self.prenom or ""
        ville = self.ville or ""
        typo = self.typo or ""
        stage = self.stage or "initial"

        prompt = f"""Tu es Daniel, conseiller immobilier chez Vianova. Tu échanges avec un prospect via WhatsApp.

Contexte prospect :
- Prénom : {prenom}
- Ville recherchée : {ville or "inconnue"}
- Type de bien : {typo or "inconnu"}
- Stade conversation : {stage}

Historique récent :
{history_str}

Nouveau message du prospect : "{original}"

RÈGLE CRITIQUE ANTI-HALLUCINATION :
- Tu NE DOIS JAMAIS extraire ni utiliser des mots du message du prospect dans ta réponse.
- Des mots comme "retour", "rappel", "suivi", "contact", "message" sont des FORMULES DE POLITESSE, jamais des lieux ou des noms.
- Tu CLASSIFIES uniquement l'intention : OUI, NON, CONTINUER ou PAUSE.
- Ignore toutes les formules de politesse (Bonjour, Merci pour ce retour, Bonne journée, etc.)

EXEMPLES CRITIQUES :
✅ "Bonjour, Merci pour ce retour. Oui toujours." → intent=OUI ("retour" = politesse, "oui toujours" = confirmation)
✅ "Merci du rappel, oui je cherche encore" → intent=OUI
✅ "Bonjour ! Avec plaisir, ça m'intéresse" → intent=OUI
✅ "Merci pour votre suivi. Non finalement" → intent=NON
✅ "Bonsoir, merci. Pas pour l'instant" → intent=NON
✅ "Merci bien, j'ai trouvé entre temps" → intent=NON

Analyse ce message et réponds UNIQUEMENT avec un JSON sur une seule ligne :
{{"intent": "NON|OUI|CONTINUER|PAUSE", "response": "ta réponse (max 2-3 phrases, vide si PAUSE)"}}

Règles intent :
- NON : prospect ne cherche plus, a trouvé, n'est plus intéressé → réponse de clôture chaleureuse
- OUI : prospect confirme être en recherche active → réponse enthousiaste qui relance
- PAUSE : prospect demande si tu es une IA/robot/bot, remet en cause ton humanité, OU pose une question totalement hors sujet (météo, sport, politique, recettes, blagues, santé, vie perso, etc.) → response vide
- CONTINUER : tout autre cas lié à l'immobilier, au projet, au budget, à la ville, aux délais (question, hésitation, objection, info partielle) → réponse adaptée

Règles réponse :
- Toujours vouvoyer
- Jamais mentionner l'IA ou les outils
- Court (2-3 phrases max)
- Naturel et chaleureux
- Rester dans le sujet immobilier
- Ne JAMAIS interpoler un mot du message du prospect dans la réponse"""

        try:
            resp = _req.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json"
                },
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 200,
                    "messages": [{"role": "user", "content": prompt}]
                },
                timeout=8
            )
            if resp.status_code == 200:
                rjson = resp.json()
                raw = rjson["content"][0]["text"].strip()
                # Tracker le coût
                try:
                    usage = rjson.get("usage", {})
                    in_tok  = usage.get("input_tokens", 0)
                    out_tok = usage.get("output_tokens", 0)
                    # Prix claude-haiku-4-5 : $0.80/MTok input, $4.00/MTok output
                    cost_usd = (in_tok * 0.0000008) + (out_tok * 0.000004)
                    import datetime as _dt, os as _os
                    _cost_file = _os.path.join(_os.path.dirname(__file__), "llm_costs.json")
                    try:
                        with open(_cost_file, "r") as _cf:
                            _costs = _json.load(_cf)
                    except Exception:
                        _costs = {"total_calls": 0, "total_input_tokens": 0, "total_output_tokens": 0, "total_cost_usd": 0.0, "calls": []}
                    _costs["total_calls"] += 1
                    _costs["total_input_tokens"] += in_tok
                    _costs["total_output_tokens"] += out_tok
                    _costs["total_cost_usd"] = round(_costs.get("total_cost_usd", 0) + cost_usd, 6)
                    _costs["calls"].append({
                        "ts": _dt.datetime.now().isoformat(),
                        "phone": self.phone,
                        "stage": self.stage,
                        "in_tok": in_tok,
                        "out_tok": out_tok,
                        "cost_usd": round(cost_usd, 6)
                    })
                    # Garder seulement les 500 derniers appels
                    _costs["calls"] = _costs["calls"][-500:]
                    with open(_cost_file, "w") as _cf:
                        _json.dump(_costs, _cf)
                except Exception as _ce:
                    logger.warning("[llm_costs] erreur tracking: %s", _ce)
                # Extraire le JSON même si du texte l'entoure
                m = re.search(r'\{.*\}', raw, re.DOTALL)
                if m:
                    parsed = _json.loads(m.group())
                    intent = parsed.get("intent", "CONTINUER").upper()
                    response = parsed.get("response", "").strip()
                    logger.info(f"[llm_fallback] intent={intent!r} pour {self.phone}")
                    if intent == "PAUSE":
                        logger.info(f"[llm_fallback] PAUSE détecté (question IA) pour {self.phone}")
                        return "__PAUSE__", ""
                    if intent == "NON":
                        return self._branche_non()
                    if intent == "OUI":
                        return self._branche_oui()
                    if response:
                        from tools.off_context import store_response
                        store_response(self.memory, response)
                        return response, ""
            logger.warning(f"[llm_fallback] API error {resp.status_code}")
        except Exception as _e:
            logger.warning(f"[llm_fallback] Exception: {_e}")

        return "__PAUSE__", ""

    def _branche_oui(self) -> Tuple[str, str]:
        """Prospect intéressé - cherche stock et propose RDV.
        RÈGLE : si un stock positif a déjà été annoncé dans cette conversation,
        on réutilise le message mis en cache - on ne re-requête JAMAIS l'API
        pour éviter de contredire ce qu'on a dit précédemment.
        """
        logger.info(f"[branche_oui] ville={self.ville!r} typo={self.typo!r}")

        # Vérifier si on a déjà annoncé un stock disponible dans cette conversation
        cached_stock_msg = self.memory.data.get("lead_info", {}).get("_stock_msg_cache")
        if cached_stock_msg:
            logger.info("[branche_oui] Utilisation du stock en cache (pas de re-requête API)")
            stock_msg = cached_stock_msg
        else:
            stock, stock_msg = get_stock(self.ville, self.typo)
            # Mettre en cache uniquement si le stock est positif (disponible)
            # → si pas disponible, on ne cache pas pour pouvoir re-tester plus tard
            if stock.get("total_lots", 0) > 0:
                self.memory.update_lead_info(_stock_msg_cache=stock_msg)

        formulations = _sc_get('rdv_propose') or [
            "Pour vous conseiller valablement et affiner vos critères, je vous propose un rendez-vous téléphonique. Seriez-vous disponible prochainement ?",
            "Pour aller plus loin et vous présenter ce qui correspond vraiment à votre projet, un appel vous conviendrait ?",
            "Pour affiner vos critères et vous conseiller au mieux, je vous suggère un court échange téléphonique. Seriez-vous disponible prochainement ?",
        ]
        rdv = random.choice(formulations)
        self.memory.set_stage("rdv_propose")
        self.memory.save()
        store_response(self.memory, stock_msg + " " + rdv)
        return stock_msg, rdv

    def _branche_non(self) -> Tuple[str, str]:
        self.memory.set_stage("attente_trouve")
        self.memory.save()
        return _sc_get('branche_non', 0) or "Je comprends. Avez-vous trouvé votre bonheur de votre côté ?", ""


if __name__ == "__main__":
    agent = VianovaAgent("test_999")
    agent.memory.update_lead_info(prenom="Sophie", ville="", typo="")
    agent.ville = ""
    agent.typo = ""
    print("=== Test contexte ville ===")
    agent.memory.add_message("assistant", "Super ! Pouvez-vous me confirmer la ville et le type de bien recherché ?")
    r1, r2 = agent.process_message("Paris")
    print("Réponse à 'Paris':", r1, "|", r2)
    import pathlib
    f = pathlib.Path("conversations/test_999.json")
    if f.exists(): f.unlink()
