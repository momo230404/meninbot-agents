#!/usr/bin/env python3
"""Agent WhatsApp Miizy — Workflow exact + gestion objections style Adam."""

import json
import logging
import os
import re
import sys
import unicodedata
import requests
from datetime import datetime, timedelta
from pathlib import Path
from typing import Tuple, Optional

logger = logging.getLogger("miizy_agent")
sys.path.insert(0, str(Path(__file__).parent))

CONFIG = json.load(open(Path(__file__).parent / "config.json"))
MIIZY_CFG = CONFIG.get("miizy", {})
CALENDLY_LINK = MIIZY_CFG.get("calendly_link", "https://calendly.com/miizy")

SESSION_TTL = 7 * 24 * 3600  # 7 jours

_CONFIG_PATH = Path(__file__).parent / "config.json"

def _get_llm_config() -> dict:
    """Relit config.json pour récupérer la config LLM à chaud (sans redémarrer)."""
    try:
        cfg = json.loads(_CONFIG_PATH.read_text())
        return cfg.get("llm", {})
    except Exception:
        return {}

def _call_llm(system_prompt: str, user_prompt: str, max_tokens: int = 250) -> str:
    """
    Appelle le LLM configuré (OpenAI ou Anthropic) et retourne le texte généré.
    Lève RuntimeError si crédit insuffisant.
    """
    llm = _get_llm_config()
    provider = llm.get("provider", "anthropic").lower()
    api_key = llm.get("api_key") or os.environ.get("ANTHROPIC_API_KEY", "")
    model = llm.get("model", "gpt-4o-mini" if provider == "openai" else "claude-haiku-4-5-20251001")

    if not api_key:
        raise RuntimeError("CREDIT_INSUFFISANT: Aucune clé API configurée")

    if provider == "openai":
        resp = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": model, "max_tokens": max_tokens,
                  "messages": [{"role": "system", "content": system_prompt},
                                {"role": "user", "content": user_prompt}]},
            timeout=15,
        )
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"].strip()
        err = resp.json().get("error", {}).get("message", "") if resp.headers.get("content-type","").startswith("application/json") else ""
        if "quota" in err.lower() or "billing" in err.lower() or "insufficient" in err.lower():
            raise RuntimeError(f"CREDIT_INSUFFISANT: {err[:120]}")
        raise RuntimeError(f"OpenAI error {resp.status_code}: {err[:80]}")

    else:  # anthropic
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": model, "max_tokens": max_tokens,
                  "system": system_prompt,
                  "messages": [{"role": "user", "content": user_prompt}]},
            timeout=15,
        )
        if resp.status_code == 200:
            return resp.json()["content"][0]["text"].strip()
        err = resp.json().get("error", {}).get("message", "") if resp.headers.get("content-type","").startswith("application/json") else ""
        if "credit" in err.lower() or "balance" in err.lower():
            raise RuntimeError(f"CREDIT_INSUFFISANT: {err[:120]}")
        raise RuntimeError(f"Anthropic error {resp.status_code}: {err[:80]}")

# ══════════════════════════════════════════════════════════════════════════════
# MESSAGES EXACTS DU WORKFLOW (jamais modifiés par le LLM)
# ══════════════════════════════════════════════════════════════════════════════

def _MESSAGES() -> dict:
    return {
        "A1": (
            "Ok super ! Connaissez-vous Miizy ?\n"
            "Une plateforme créée par des pros de l'immo, pour des pros de l'immo "
            "— 40 000 lots neufs en France, CRM complet et multidiffusion de vos annonces.\n\n"
            "Cerise sur le gâteau, il y a même une version gratuite !\n\n"
            "Je peux vous montrer ça en 20 min — vous seriez dispo prochainement ?"
        ),
        "B1": (
            "Ok super !\n"
            "Connaissez-vous Miizy ? Une plateforme pensée par des pros de l'immo, "
            "pour des pros de l'immo — 40 000 lots neufs en France, CRM complet "
            "et multidiffusion de vos annonces.\n\n"
            "Cerise sur le gâteau : on vous propose aussi une version gratuite.\n\n"
            "Je peux vous montrer ça en 20 min — vous seriez dispo prochainement ?"
        ),
        "A2_NON": (
            "Je comprends, je ne vous retiens pas — sachez simplement que Miizy centralise "
            "votre stock et CRM en un seul outil pour diversifier vers le neuf, sécuriser "
            "vos mandats et booster votre chiffre d'affaires.\n"
            "Et le tout 100% offert sur notre plateforme."
        ),
        "B2_NON": (
            "Je comprends, je ne vous retiens pas — sachez simplement que Miizy centralise "
            "votre stock et CRM en un seul outil pour diversifier vers le neuf, sécuriser "
            "vos mandats et booster votre chiffre d'affaires.\n"
            "Et le tout 100% offert sur notre plateforme."
        ),
        "FINAL_A": (
            "Super ! À très vite ! N'hésitez pas à me solliciter si besoin d'ici notre échange."
        ),
        "FINAL_B": (
            "Super ! À très vite ! N'hésitez pas à me solliciter si besoin d'ici notre échange."
        ),
        "RELANCE_A": (
            "Très bien, dans ce cas je vous rappelle dans la journée pour convenir "
            "d'un créneau qui vous convient."
        ),
        "RELANCE_B": (
            "Très bien, dans ce cas je vous rappelle dans la journée pour convenir "
            "d'un créneau qui vous convient."
        ),
    }

# Table de routing NON uniquement (OUI → créneaux Calendar, géré dans process_message)
WORKFLOW_ROUTING_NON = {
    "WAITING_RDV_A": ("A2_NON", "DONE"),
    "WAITING_RDV_B": ("B2_NON", "DONE"),
    "WAITING_CALENDLY_A": ("RELANCE_A", "DONE"),
    "WAITING_CALENDLY_B": ("RELANCE_B", "DONE"),
}


# ══════════════════════════════════════════════════════════════════════════════
# DÉTECTION REGEX
# ══════════════════════════════════════════════════════════════════════════════

def _normalize(txt: str) -> str:
    """Normalise : minuscule + suppression diacritiques."""
    nfkd = unicodedata.normalize("NFD", txt.lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def detect_branch(txt: str) -> Optional[str]:
    """Détecte NEUF (→ A) ou ANCIEN (→ B). Retourne 'A', 'B' ou None."""
    t = _normalize(txt)
    # Si c'est une question (ex: "Vous travaillez sur du neuf ?"), ce n'est pas une réponse → None
    if txt.strip().endswith("?"):
        return None
    if re.search(r"^\s*(vous\s+travaillez|vous\s+faites|vous\s+[eê]tes|est[\s-]ce\s+que|quel|qu[''']est)", t):
        return None
    # Neuf OU mixte → branche A
    if re.search(
        r"\b(neuf|les deux|les 2|mixte|nouveau|nouvelle construction|vefa|"
        r"promoteur|promotion|programme neuf|immobilier neuf|new|"
        r"neuf.*ancien|ancien.*neuf|que du neuf|surtout neuf|uniquement neuf)\b",
        t
    ):
        return "A"
    # Ancien uniquement → branche B
    if re.search(
        r"\b(ancien|ancienne|vieux|vieille|existant|secondaire|revente|occasion|"
        r"de l ancien|que l ancien|que de l ancien|surtout ancien|uniquement ancien)\b",
        t
    ):
        return "B"
    return None


def detect_yes_no(txt: str) -> Optional[str]:
    """Détecte OUI / NON. Retourne 'OUI', 'NON' ou None si ambigu."""
    t = _normalize(txt)

    # POSITIF
    if re.search(
        r"\b(oui|yes|yep|ouais|ok|okay|bien sur|absolument|exactement|parfait|super|"
        r"nickel|volontiers|avec plaisir|carrément|carrement|tout a fait|tout à fait|"
        r"affirmatif|positif|je veux|ca marche|c est bon|go|allons y|1|"
        r"j ai pris|j'ai pris|pris|reserve|reservé|c est fait|c'est fait|rdv pris|"
        r"j ai reserve|j'ai réservé|done|bonne idee|pourquoi pas)\b",
        t
    ) or re.search(r"[👍✅]", txt):
        return "OUI"

    # NÉGATIF
    if re.search(
        r"\b(non|no|nope|nan|pas vraiment|pas pour|pas interesse|pas maintenant|"
        r"merci mais|je ne|j'ai pas|j ai pas|pas le temps|pas besoin|deja|"
        r"je connais|connais deja|0|pas du tout|absolument pas|jamais|bof|"
        r"pas encore|pas trouve|pas de creneau|pas disponible|rien|aucun)\b",
        t
    ) or re.search(r"[👎❌]", txt):
        return "NON"

    return None


def _detect_objection(txt: str) -> Optional[str]:
    """Détecte le type d'objection dans un message du prospect."""
    t = _normalize(txt)

    # Pas intéressé
    if re.search(
        r"\b(pas interesse|pas interess|non interesse|pas pour moi|"
        r"ca m interesse pas|ca ne m interesse pas|ne m interesse|"
        r"m interesse pas|sans interet|pas concerne|pas concern)\b", t
    ):
        return "pas_interesse"

    # Mauvais moment / pas disponible
    if re.search(
        r"\b(pas le bon moment|pas maintenant|plus tard|dans quelques|"
        r"en ce moment|mauvais moment|pas dispo en ce moment|"
        r"trop occupe|trop busy|chargé en ce|charge en ce|revenez|rappel"
        r"ez.moi|rappeler plus tard|pas le moment)\b", t
    ):
        return "mauvais_moment"

    # Demande de mail / email
    if re.search(
        r"\b(envoyez|envoyer|par mail|par email|par e.mail|un mail|un email|"
        r"ecrivez|ecrivez.moi|contactez.moi par|envoi.moi|send me|par message|"
        r"laissez.moi|laissez un)\b", t
    ) and re.search(r"\b(mail|email|e.mail|message|mp|dm)\b", t):
        return "demande_mail"

    # Déjà suivi / accompagné
    if re.search(
        r"\b(deja suivi|deja accompagne|j ai deja|j'ai deja|deja un|deja une|"
        r"je travaille deja avec|j ai quelqu|on a deja|deja equipe|"
        r"on est deja|je suis deja avec|j utilise deja)\b", t
    ):
        return "deja_suivi"

    return None


# ══════════════════════════════════════════════════════════════════════════════
# CLASSIFICATION LLM (fallback — uniquement OUI/NON/UNCLEAR)
# ══════════════════════════════════════════════════════════════════════════════

def _classify_with_llm(user_msg: str, step: str, history: list) -> dict:
    """
    Classifie l'intention du prospect via le LLM configuré (OpenAI ou Anthropic).
    Retourne {"intention": "OUI"|"NON"|"UNCLEAR", "clarification": str|None}
    """
    step_desc = {
        "WAITING_NEUF_ANCIEN": (
            "Le prospect doit indiquer s'il travaille sur du NEUF, de l'ANCIEN, ou les deux. "
            "Réponds 'A' si NEUF ou les deux, 'B' si ANCIEN uniquement."
        ),
        "WAITING_RDV_A": "Le prospect doit dire s'il veut un RDV de 20 min pour voir Miizy (OUI/NON).",
        "WAITING_CALENDLY_A": "Le prospect doit dire si un créneau Calendly lui a convenu (OUI/NON).",
        "WAITING_RDV_B": "Le prospect doit dire s'il veut un RDV de 20 min pour voir Miizy (OUI/NON).",
        "WAITING_CALENDLY_B": "Le prospect doit dire si un créneau Calendly lui a convenu (OUI/NON).",
    }.get(step, "Détecter l'intention du prospect.")

    is_branch_step = step in ("WAITING_NEUF_ANCIEN",)
    hist_str = "\n".join(
        f"{'Prospect' if r == 'user' else 'Agent'}: {c[:150]}"
        for r, c in history[-6:]
    ) or "(début de conversation)"

    fmt = ('{"intention": "A"|"B"|"UNCLEAR", "clarification": "...ou null"}'
           if is_branch_step else
           '{"intention": "OUI"|"NON"|"UNCLEAR", "clarification": "...ou null"}')

    system = "Tu es un classificateur d'intention dans une conversation WhatsApp commerciale immobilier. Réponds UNIQUEMENT en JSON valide."
    user_prompt = f"""ÉTAPE : {step_desc}
HISTORIQUE :
{hist_str}
NOUVEAU MESSAGE : "{user_msg}"
RÈGLES :
- Signal positif/accord implicite → OUI{"ou A" if is_branch_step else ""}
- Refus/hésitation forte/désintérêt → NON{"ou B" if is_branch_step else ""}
- UNCLEAR seulement si impossible → ajoute une courte question de clarification
Réponds : {fmt}"""

    try:
        raw = _call_llm(system, user_prompt, max_tokens=100)
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            parsed = json.loads(m.group())
            intention = parsed.get("intention", "UNCLEAR").upper()
            logger.info(f"[Miizy LLM] step={step} intention={intention}")
            return {"intention": intention, "clarification": parsed.get("clarification") or None}
    except RuntimeError:
        raise
    except Exception as e:
        logger.warning(f"[Miizy LLM] Exception: {e}")

    return {"intention": "UNCLEAR", "clarification": None}


def _generate_adam_response(
    user_msg: str,
    step: str,
    session: "MiizySession",
    objection_type: str,
) -> "Tuple[str, str]":
    """Génère une réponse Adam via le LLM configuré (OpenAI ou Anthropic)."""
    history = session.get("history", [])
    hist_str = "\n".join(
        f"{'Prospect' if h['role'] == 'user' else 'Adam'}: {h['content'][:200]}"
        for h in history[-8:]
    ) or "(premier message)"
    prenom = session.prenom

    _OBJECTION_GUIDANCE = {
        "pas_interesse": (
            "Reformule UN bénéfice concret de Miizy (ex : 40k lots neufs + version gratuite), "
            "puis pose une question ouverte sur leur activité actuelle. Ne contre-argumente pas. Reste détendu."
        ),
        "mauvais_moment": (
            "Accepte le timing avec élégance. Demande quand serait le meilleur moment. "
            "Propose de revenir à la date qu'ils choisissent."
        ),
        "demande_mail": (
            "Accepte mais réoriente vers l'appel de 5 min : 'un appel de 5 min vous donnera plus qu'un mail de 10 pages.' "
            "Reste chaleureux, pas insistant."
        ),
        "deja_suivi": (
            "Valorise leur organisation. Souligne ce que Miizy fait qu'aucun autre ne fait : "
            "40k lots neufs + CRM + version gratuite. Propose 20 min pour voir si ça complète ce qu'ils ont."
        ),
        "inconnu": (
            "Réponds naturellement en t'appuyant sur le contexte. Si le prospect n'a pas encore répondu à la question "
            "principale, replonge-y subtilement. Sinon, avance vers le RDV. Simple, chaleureux, pas insistant."
        ),
    }
    guidance = _OBJECTION_GUIDANCE.get(objection_type, _OBJECTION_GUIDANCE["inconnu"])

    system_prompt = (
        "Tu es Adam, commercial terrain chez Miizy. Tu relances des professionnels de l'immobilier sur WhatsApp.\n"
        "PERSONA : Audace Empathique — assumes l'intrusion frontalement, parles cash, phrases courtes, max 2 emojis.\n"
        "MIIZY : 40 000 lots neufs en France + CRM complet + multidiffusion annonces — version gratuite dispo.\n"
        "OBJECTIF : obtenir un RDV de 20 min (visio ou appel).\n"
        "RÈGLE ABSOLUE : propose la visio D'ABORD. Jamais fusionner visio + 'pari gratuit' dans le même message.\n"
        "FORMAT : 2-4 phrases max. Pas de liste. Terminer par une question/invitation RDV."
    )
    user_prompt = (
        f"CONVERSATION :\n{hist_str}\n\n"
        f"NOUVEAU MESSAGE : \"{user_msg}\"\n"
        f"TYPE : {objection_type} | PRÉNOM : {prenom or '(inconnu)'} | ÉTAPE : {step}\n"
        f"GUIDANCE : {guidance}\n\n"
        "Génère UNE réponse en français, 2-4 phrases."
    )

    try:
        reply = _call_llm(system_prompt, user_prompt, max_tokens=250)
        logger.info(f"[Miizy][Adam] objection={objection_type} reply={reply[:80]}")
        session.add_history("assistant", reply)
        return reply, ""
    except RuntimeError:
        raise
    except Exception as e:
        logger.warning(f"[Miizy][Adam] Exception: {e}")

    # Fallback de secours sans LLM
    p = f" {prenom}" if prenom else ""
    fallback = f"Bonne question{p} — je vous réponds dans la journée. Vous seriez dispo pour un rapide échange cette semaine ?"
    session.add_history("assistant", fallback)
    return fallback, ""


def _track_llm_cost(usage: dict, label: str):
    """Trace le coût LLM dans llm_costs.json."""
    in_tok = usage.get("input_tokens", 0)
    out_tok = usage.get("output_tokens", 0)
    cost_usd = (in_tok * 0.0000008) + (out_tok * 0.000004)
    cost_file = Path(__file__).parent / "llm_costs.json"
    try:
        costs = json.loads(cost_file.read_text()) if cost_file.exists() else {
            "total_calls": 0, "total_input_tokens": 0,
            "total_output_tokens": 0, "total_cost_usd": 0.0, "calls": []
        }
    except Exception:
        costs = {"total_calls": 0, "total_input_tokens": 0,
                 "total_output_tokens": 0, "total_cost_usd": 0.0, "calls": []}
    costs["total_calls"] += 1
    costs["total_input_tokens"] += in_tok
    costs["total_output_tokens"] += out_tok
    costs["total_cost_usd"] = round(costs.get("total_cost_usd", 0) + cost_usd, 6)
    costs["calls"] = costs["calls"][-499:] + [{
        "ts": datetime.now().isoformat(), "label": label,
        "in_tok": in_tok, "out_tok": out_tok, "cost_usd": round(cost_usd, 6),
    }]
    cost_file.write_text(json.dumps(costs))


# ══════════════════════════════════════════════════════════════════════════════
# SESSION FICHIER (remplace Redis)
# ══════════════════════════════════════════════════════════════════════════════

_SESSIONS_DIR = Path(__file__).parent / "miizy_sessions"
_SESSIONS_DIR.mkdir(exist_ok=True)
SESSION_TTL_DAYS = 7

# Déduplication messages en mémoire (remplace Redis miizy:msgid:*)
_MSG_DEDUP: dict = {}

def _check_dedup(msg_id: str) -> bool:
    """Retourne True si message déjà traité (doublon)."""
    if not msg_id:
        return False
    now = datetime.now().timestamp()
    expired = [k for k, t in list(_MSG_DEDUP.items()) if now - t > 120]
    for k in expired:
        _MSG_DEDUP.pop(k, None)
    if msg_id in _MSG_DEDUP:
        return True
    _MSG_DEDUP[msg_id] = now
    return False


def load_session_file(phone: str) -> dict:
    """Charge la session depuis le fichier JSON. Retourne le dict de données."""
    f = _SESSIONS_DIR / f"{phone}.json"
    try:
        if f.exists():
            data = json.loads(f.read_text(encoding="utf-8"))
            last = data.get("last_updated", "")
            if last:
                delta = datetime.now() - datetime.fromisoformat(last)
                if delta.days >= SESSION_TTL_DAYS:
                    logger.info(f"[MiizySession] Session expirée ({phone}) — reset")
                    f.unlink(missing_ok=True)
                    return _default_session(phone)
            return data
    except Exception as e:
        logger.warning(f"[MiizySession] Lecture {phone}: {e}")
    return _default_session(phone)


def save_session_file(phone: str, data: dict):
    """Sauvegarde la session dans le fichier JSON."""
    f = _SESSIONS_DIR / f"{phone}.json"
    try:
        data["last_updated"] = datetime.now().isoformat()
        f.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        logger.warning(f"[MiizySession] Écriture {phone}: {e}")


def delete_session_file(phone: str):
    """Supprime le fichier de session (reset conversation)."""
    f = _SESSIONS_DIR / f"{phone}.json"
    try:
        f.unlink(missing_ok=True)
    except Exception:
        pass


def _default_session(phone: str) -> dict:
    return {"phone": phone, "prenom": "", "step": "WAITING_NEUF_ANCIEN",
            "branch": None, "history": [], "last_updated": datetime.now().isoformat()}


class MiizySession:
    """Gère la session d'un prospect Miizy via fichier JSON local."""

    def __init__(self, phone: str, redis_client=None):  # redis_client ignoré (compat)
        self.phone = phone
        self.data = load_session_file(phone)

    def save(self):
        save_session_file(self.phone, self.data)

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value
        self.save()

    def update(self, **kwargs):
        self.data.update(kwargs)
        self.save()

    @property
    def step(self) -> str:
        return self.data.get("step", "WAITING_NEUF_ANCIEN")

    @property
    def prenom(self) -> str:
        return self.data.get("prenom", "")

    def add_history(self, role: str, content: str):
        history = self.data.get("history", [])
        history.append({"role": role, "content": content[:300]})
        self.data["history"] = history[-20:]
        self.save()


# ══════════════════════════════════════════════════════════════════════════════
# AGENT PRINCIPAL
# ══════════════════════════════════════════════════════════════════════════════

class MiizyAgent:
    """Agent WhatsApp Miizy — workflow exact + fallback LLM classification."""

    def __init__(self, phone: str, redis_client):
        self.phone = phone
        self.session = MiizySession(phone, redis_client)
        self.MSGS = _MESSAGES()

    def set_prenom(self, prenom: str):
        if prenom and not self.session.prenom:
            self.session.set("prenom", prenom)

    # Conservé pour compatibilité avec l'ancien code
    def get_initial_message(self) -> Tuple[str, str]:
        """Non utilisé dans le nouveau workflow (template envoyé par campagne)."""
        self.session.set("step", "WAITING_NEUF_ANCIEN")
        return "", ""

    def _propose_slots(self, branch: str) -> Tuple[str, str]:
        """Récupère les créneaux Calendar et les propose naturellement."""
        try:
            from tools.miizy_calendar import get_miizy_slots
            slots = get_miizy_slots(count=3)
        except Exception as e:
            logger.warning(f"[Miizy] Erreur miizy_calendar: {e}")
            slots = []

        prenom = self.session.prenom
        p = f" {prenom}" if prenom else ""
        next_step = "WAITING_CRENEAU_A" if branch == "A" else "WAITING_CRENEAU_B"

        if not slots:
            # Pas de créneaux disponibles → relance manuelle
            reply = (f"Avec plaisir{p} ! Mon agenda est chargé en ce moment, "
                     f"je vous rappelle dans la journée pour trouver un moment qui vous convient.")
            self.session.update(step="DONE")
            self.session.add_history("assistant", reply)
            return reply, ""

        # Stocker les créneaux proposés pour les retrouver lors du choix
        self.session.set("slots_proposes", slots)
        self.session.set("step", next_step)

        slots_str = "\n".join(f"• {s}" for s in slots)
        reply = (f"Avec plaisir{p} ! Voici mes prochaines disponibilités :\n\n"
                 f"{slots_str}\n\n"
                 f"L'un de ces créneaux vous conviendrait ?")
        self.session.add_history("assistant", reply)
        return reply, ""

    def _confirm_slot(self, slot: str) -> Tuple[str, str]:
        """Confirme le créneau choisi et crée l'événement Calendar."""
        prenom = self.session.prenom
        p = f" {prenom}" if prenom else ""
        try:
            from tools.miizy_calendar import create_miizy_event
            create_miizy_event(self.phone, slot, prenom)
        except Exception as e:
            logger.warning(f"[Miizy] Erreur création événement: {e}")
        self.session.update(step="DONE")
        reply = (f"C'est noté{p} ! Je confirme notre échange le {slot}. "
                 f"Je vous appelle directement sur ce numéro. À très vite ! 👋")
        self.session.add_history("assistant", reply)
        return reply, ""

    def process_message(self, text: str, msg_id: str = "") -> Tuple[str, str]:
        """Traite un message entrant. Retourne (reply, "")."""

        # Anti-doublon msg_id
        if _check_dedup(msg_id):
            logger.info(f"[Miizy] doublon msg_id={msg_id} ignoré")
            return "", ""

        txt = text.strip()
        step = self.session.step

        # Compatibilité : INIT et anciens états → WAITING_NEUF_ANCIEN
        if step in ("INIT", "ATTENTE_TYPE_ACTIVITE"):
            step = "WAITING_NEUF_ANCIEN"
            self.session.set("step", step)
        elif step in ("PITCH_ENVOYE",):
            step = "WAITING_RDV_A"
            self.session.set("step", step)
        elif step in ("ATTENTE_CONFIRMATION_CALENDLY",):
            step = "WAITING_CALENDLY_A"
            self.session.set("step", step)
        elif step in ("RELANCE_APRES_NON", "FERME"):
            step = "DONE"
            self.session.set("step", step)

        # Enregistrer le message dans l'historique
        self.session.add_history("user", txt)

        logger.info(f"[Miizy] {self.phone} step={step} msg='{txt[:60]}'")

        t_norm = _normalize(txt)

        # ── "VOUS ÊTES QUI ?" → présentation rapide ─────────────────────────
        _QUI = [
            r"\bvous\s+[eê]tes\s+qui\b", r"\bc['']est\s+qui\b",
            r"\bqui\s+[eê]tes[\s-]vous\b", r"\bqui\s+es[\s-]tu\b",
            r"\bde\s+(qui|la\s+part\s+de\s+qui)\b",
            r"\bje\s+(vous|te)\s+connais\s+pas\b",
            r"\bvous\s+[eê]tes\s+de\s+qui\b",
            r"\bc['']est\s+quoi\s+miizy\b",
        ]
        if any(re.search(p, txt, re.IGNORECASE) for p in _QUI):
            prenom = self.session.prenom
            p = f" {prenom}" if prenom else ""
            reply = f"C'est Alex de Miizy{p} 👋 On avait échangé au sujet de votre activité immobilière."
            self.session.add_history("assistant", reply)
            return reply, ""

        # ── HORS SUJET ÉVIDENT → silence ────────────────────────────────────
        _HORS_SUJET = [
            r"\b(météo|football|sport|recette|cuisine|film|musique|politique|"
            r"blague|jeu\s+vid[ée]o|voiture|voyage|vacances)\b",
        ]
        if any(re.search(p, t_norm, re.IGNORECASE) for p in _HORS_SUJET):
            logger.info(f"[Miizy] Hors sujet détecté — silence pour {self.phone}")
            return "", ""

        # ── ÉTAPE 0 : détecter NEUF ou ANCIEN ──────────────────────────────
        if step == "WAITING_NEUF_ANCIEN":
            branch = detect_branch(txt)

            if not branch:
                # Avant le LLM : vérifier si c'est une objection → répondre style Adam
                objection = _detect_objection(txt)
                if objection:
                    return _generate_adam_response(txt, step, self.session, objection)

                result = _classify_with_llm(
                    txt, "WAITING_NEUF_ANCIEN",
                    [(h["role"], h["content"]) for h in self.session.get("history", [])]
                )
                intention = result["intention"]

                if intention == "UNCLEAR":
                    # Pas de silence : l'agent génère une réponse Adam contextuelle
                    logger.info(f"[Miizy] UNCLEAR neuf/ancien — réponse Adam pour {self.phone}")
                    return _generate_adam_response(txt, step, self.session, "inconnu")

                branch = "A" if intention == "A" else "B"

            self.session.update(branch=branch, step="WAITING_RDV_A" if branch == "A" else "WAITING_RDV_B")
            msg_key = "A1" if branch == "A" else "B1"
            reply = self.MSGS[msg_key]
            self.session.add_history("assistant", reply)
            return reply, ""

        # ── WAITING_RDV : OUI → créneaux Calendar, NON → message de sortie ───
        if step in ("WAITING_RDV_A", "WAITING_RDV_B"):
            detection = detect_yes_no(txt)
            if not detection:
                # Vérifier si c'est une objection avant de classer OUI/NON
                objection = _detect_objection(txt)
                if objection:
                    return _generate_adam_response(txt, step, self.session, objection)

                result = _classify_with_llm(
                    txt, step,
                    [(h["role"], h["content"]) for h in self.session.get("history", [])]
                )
                intention = result["intention"]
                if intention == "UNCLEAR":
                    logger.info(f"[Miizy] UNCLEAR rdv — réponse Adam pour {self.phone}")
                    return _generate_adam_response(txt, step, self.session, "inconnu")
                detection = intention

            if detection == "OUI":
                branch = "A" if step == "WAITING_RDV_A" else "B"
                return self._propose_slots(branch)

            # NON
            msg_key, next_step = WORKFLOW_ROUTING_NON[step]
            reply = self.MSGS[msg_key]
            self.session.update(step=next_step)
            self.session.add_history("assistant", reply)
            return reply, ""

        # ── WAITING_CRENEAU : le prospect choisit un créneau ───────────────
        if step in ("WAITING_CRENEAU_A", "WAITING_CRENEAU_B"):
            slots = self.session.get("slots_proposes", [])
            try:
                from tools.miizy_calendar import detect_chosen_slot
                chosen = detect_chosen_slot(txt, slots)
            except Exception:
                chosen = None

            if chosen:
                return self._confirm_slot(chosen)

            # Pas compris → on repose la question avec les créneaux
            if not slots:
                return self._propose_slots("A" if step == "WAITING_CRENEAU_A" else "B")

            slots_str = "\n".join(f"• {s}" for s in slots)
            clarif = f"Je n'ai pas bien saisi votre choix — voici les créneaux proposés :\n\n{slots_str}\n\nLequel vous convient ?"
            self.session.add_history("assistant", clarif)
            return clarif, ""

        # ── WAITING_CALENDLY (compat ancienne session) → re-proposer créneaux
        if step in ("WAITING_CALENDLY_A", "WAITING_CALENDLY_B"):
            detection = detect_yes_no(txt)
            if not detection:
                objection = _detect_objection(txt)
                if objection:
                    return _generate_adam_response(txt, step, self.session, objection)
                result = _classify_with_llm(txt, step, [(h["role"], h["content"]) for h in self.session.get("history", [])])
                detection = result["intention"]
                if detection == "UNCLEAR":
                    return _generate_adam_response(txt, step, self.session, "inconnu")
            if detection == "OUI":
                branch = "A" if step == "WAITING_CALENDLY_A" else "B"
                # Confirme que le prospect a pris un créneau
                reply = self.MSGS["FINAL_A" if branch == "A" else "FINAL_B"]
                self.session.update(step="DONE")
                self.session.add_history("assistant", reply)
                return reply, ""
            msg_key, next_step = WORKFLOW_ROUTING_NON[step]
            reply = self.MSGS[msg_key]
            self.session.update(step=next_step)
            self.session.add_history("assistant", reply)
            return reply, ""

        # ── DONE : conversation fermée ──────────────────────────────────────
        if step == "DONE":
            t_norm = _normalize(txt)
            # Rouverture explicite → re-proposer des créneaux
            if re.search(
                r"\b(finalement|en fait|reconsidere|j y pense|je veux bien|"
                r"interesse|interessé|dispo|disponible|rdv|rendez.vous)\b", t_norm
            ) or detect_yes_no(txt) == "OUI":
                branch = self.session.get("branch", "A") or "A"
                return self._propose_slots(branch)
            # Message inattendu en DONE → réponse Adam légère (pas de relance lourde)
            if len(txt.strip()) > 3:
                return _generate_adam_response(txt, step, self.session, "inconnu")
            return "", ""

        # Fallback step inconnu → réponse Adam générique
        logger.warning(f"[Miizy] Step inconnu: {step} — réponse Adam générique")
        return _generate_adam_response(txt, step, self.session, "inconnu")

    def _create_callback_task(self):
        """Crée un rappel Google Calendar pour recontacter le prospect."""
        from tools.calendar_api import _get_calendar_service

        service = _get_calendar_service()
        if not service:
            logger.warning("[Miizy] Google Calendar non disponible pour tâche rappel")
            return

        now = datetime.now()
        if now.hour >= 16:
            start = (now + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
        else:
            start = (now + timedelta(hours=3)).replace(minute=0, second=0, microsecond=0)
        end = start + timedelta(minutes=30)

        prenom = self.session.prenom
        p_str = f" {prenom}" if prenom else ""
        event = {
            "summary": f"📞 Rappel Miizy —{p_str or ' ' + self.phone}",
            "description": (
                f"Prospect Miizy{p_str} à rappeler pour convenir d'un créneau de démo.\n"
                f"Tél : {self.phone}\n"
                f"Pas trouvé de créneau sur Calendly — à recontacter manuellement."
            ),
            "start": {"dateTime": start.isoformat(), "timeZone": "Europe/Paris"},
            "end": {"dateTime": end.isoformat(), "timeZone": "Europe/Paris"},
            "colorId": "5",
        }
        cfg_cal = CONFIG.get("google", {})
        cal_id = cfg_cal.get("calendar_id", "primary")
        service.events().insert(calendarId=cal_id, body=event).execute()
        logger.info(f"[Miizy] Tâche rappel créée pour {self.phone} à {start}")
