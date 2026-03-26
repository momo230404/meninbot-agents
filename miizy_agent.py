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
    Appelle Claude Haiku pour classifier l'intention.
    Retourne {"intention": "OUI"|"NON"|"UNCLEAR", "clarification": str|None}
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        logger.warning("[Miizy LLM] Pas de ANTHROPIC_API_KEY — fallback NON")
        return {"intention": "NON", "clarification": None}

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

    if is_branch_step:
        format_instructions = (
            'Réponds UNIQUEMENT en JSON : {"intention": "A"|"B"|"UNCLEAR", '
            '"clarification": "message court si UNCLEAR, sinon null"}'
        )
    else:
        format_instructions = (
            'Réponds UNIQUEMENT en JSON : {"intention": "OUI"|"NON"|"UNCLEAR", '
            '"clarification": "message court si UNCLEAR, sinon null"}'
        )

    prompt = f"""Tu analyses les réponses d'un agent immobilier dans une conversation WhatsApp commerciale.

ÉTAPE ACTUELLE : {step_desc}

HISTORIQUE :
{hist_str}

NOUVEAU MESSAGE DU PROSPECT : "{user_msg}"

RÈGLES :
- Considère tout signal positif, enthousiaste ou implicitement d'accord comme OUI{'/A' if is_branch_step else ''}.
- Considère tout refus, hésitation forte, désintérêt ou réponse négative comme NON{'/B' if is_branch_step else ''}.
- UNCLEAR uniquement si vraiment impossible à déterminer → fournis une question de clarification très courte (1 phrase).
- Analyse le sous-texte, pas juste les mots.

{format_instructions}"""

    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 100,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=8,
        )
        if resp.status_code == 200:
            raw = resp.json()["content"][0]["text"].strip()
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            if m:
                parsed = json.loads(m.group())
                intention = parsed.get("intention", "UNCLEAR").upper()
                clarification = parsed.get("clarification") or None
                try:
                    _track_llm_cost(resp.json().get("usage", {}), "miizy_classify")
                except Exception:
                    pass
                logger.info(f"[Miizy LLM] step={step} intention={intention}")
                return {"intention": intention, "clarification": clarification}
        err_body = resp.json() if resp.headers.get("content-type","").startswith("application/json") else {}
        err_msg = err_body.get("error", {}).get("message", "") if isinstance(err_body, dict) else ""
        if "credit" in err_msg.lower() or "balance" in err_msg.lower():
            logger.error(f"[Miizy LLM] Crédit Anthropic insuffisant")
            raise RuntimeError(f"CREDIT_INSUFFISANT: {err_msg[:120]}")
        logger.warning(f"[Miizy LLM] API error {resp.status_code}: {err_msg[:80]}")
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
    """
    Génère une réponse humaine style Adam (Miizy) face à une objection.
    Persona : L'Audace Empathique + Le Pari + Transparence Radicale.
    Règle tempo : ne jamais fusionner proposition de visio ET proposition de pari.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        logger.warning("[Miizy][Adam] Pas d'ANTHROPIC_API_KEY — silence")
        return "", ""

    history = session.get("history", [])
    hist_str = "\n".join(
        f"{'Prospect' if h['role'] == 'user' else 'Adam'}: {h['content'][:200]}"
        for h in history[-8:]
    ) or "(premier message)"
    prenom = session.prenom

    _OBJECTION_GUIDANCE = {
        "pas_interesse": (
            "Reformule UN bénéfice concret de Miizy (ex : 40k lots neufs + version gratuite), "
            "puis pose une question ouverte sur leur activité actuelle. "
            "Ne contre-argumente pas directement. Reste détendu."
        ),
        "mauvais_moment": (
            "Accepte le timing avec élégance. "
            "Demande quand serait le meilleur moment ('La semaine prochaine ? Le mois prochain ?'). "
            "Propose de revenir à la date qu'ils choisissent."
        ),
        "demande_mail": (
            "Accepte mais réoriente vers l'appel de 5 min : "
            "'Je peux faire ça, mais franchement un appel de 5 min vous donnera plus qu'un mail de 10 pages.' "
            "Reste chaleureux, pas insistant."
        ),
        "deja_suivi": (
            "Valorise leur organisation ('C'est un excellent signe — les meilleurs combinent les outils'). "
            "Souligne ce que Miizy fait qu'aucun autre ne fait : 40k lots neufs + CRM + version gratuite. "
            "Propose juste 20 min pour voir si ça complète ce qu'ils ont."
        ),
        "inconnu": (
            "Le message ne rentre dans aucune case connue. Réponds de manière naturelle et humaine "
            "en t'appuyant sur le contexte de la conversation. Maintiens le fil : "
            "si le prospect n'a pas encore répondu à la question principale, replonge-y subtilement. "
            "Sinon, continue la conversation vers le RDV. Reste simple, chaleureux, pas insistant."
        ),
    }
    guidance = _OBJECTION_GUIDANCE.get(objection_type, _OBJECTION_GUIDANCE["inconnu"])

    system_prompt = (
        "Tu es Adam, commercial terrain chez Miizy. Tu relances des professionnels de "
        "l'immobilier sur WhatsApp.\n\n"
        "TON PERSONA :\n"
        "- 'L'Audace Empathique' : tu assumes l'intrusion frontalement "
        "('Je plaide coupable', 'Je préfère me faire gronder plutôt que de ne pas essayer')\n"
        "- Transparence radicale : tu parles cash, sans langue de bois\n"
        "- Phrases courtes, punchy. Max 2 emojis par message (🤝 🎯 🏆 🎁)\n\n"
        "MIIZY EN 1 LIGNE :\n"
        "40 000 lots neufs en France + CRM complet + multidiffusion annonces — version gratuite dispo.\n"
        "Objectif unique : obtenir un RDV de 20 min (visio ou appel).\n\n"
        "RÈGLE TEMPO ABSOLUE — NE JAMAIS VIOLER :\n"
        "1. D'abord : propose la visio/appel de 20 min\n"
        "2. SEULEMENT après confirmation d'intérêt → 'On prend le pari ?' "
        "(version offerte si pas convaincu)\n"
        "→ Ne JAMAIS mettre ces 2 éléments dans le même message.\n\n"
        "STYLE — exemples :\n"
        "✓ 'Ah d'accord, et vous travaillez sur quel type de biens en ce moment ?'\n"
        "✓ 'Je plaide coupable — mais 20 min pour voir Miizy, c'est vraiment peu pour ce que ça peut apporter.'\n"
        "✗ 'Pourriez-vous me préciser votre situation actuelle ?'\n\n"
        "CONTRAINTE STRICTE : 2-4 phrases max. Jamais de liste à puces. "
        "Toujours terminer par une question ou une invitation douce vers le RDV."
    )

    prompt = (
        f"CONVERSATION :\n{hist_str}\n\n"
        f"NOUVEAU MESSAGE DU PROSPECT : \"{user_msg}\"\n"
        f"TYPE D'OBJECTION : {objection_type}\n"
        f"PRÉNOM : {prenom or '(inconnu)'}\n"
        f"ÉTAPE WORKFLOW : {step}\n\n"
        f"GUIDANCE SPÉCIFIQUE : {guidance}\n\n"
        "Génère UNE réponse naturelle en français. 2-4 phrases max. "
        "Pas de liste. Terminer par une question/invitation RDV."
    )

    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 250,
                "system": system_prompt,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=10,
        )
        if resp.status_code == 200:
            reply = resp.json()["content"][0]["text"].strip()
            try:
                _track_llm_cost(resp.json().get("usage", {}), "miizy_adam_objection")
            except Exception:
                pass
            logger.info(f"[Miizy][Adam] objection={objection_type} reply={reply[:80]}")
            session.add_history("assistant", reply)
            return reply, ""
        err_body = resp.json() if resp.headers.get("content-type","").startswith("application/json") else {}
        err_msg = err_body.get("error", {}).get("message", "") if isinstance(err_body, dict) else ""
        if "credit" in err_msg.lower() or "balance" in err_msg.lower():
            logger.error(f"[Miizy][Adam] Crédit Anthropic insuffisant — {err_msg[:120]}")
            raise RuntimeError(f"CREDIT_INSUFFISANT: {err_msg[:120]}")
        logger.warning(f"[Miizy][Adam] API error {resp.status_code}: {err_msg[:80]}")
    except RuntimeError:
        raise
    except Exception as e:
        logger.warning(f"[Miizy][Adam] Exception: {e}")

    # Fallback de secours : relance douce sans LLM
    prenom = session.prenom
    p = f" {prenom}" if prenom else ""
    fallback = f"Bonne question{p} — je vous réponds dans la journée pour qu'on en discute ensemble. Vous seriez dispo pour un rapide échange cette semaine ?"
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
# SESSION REDIS
# ══════════════════════════════════════════════════════════════════════════════

class MiizySession:
    """Gère la session Redis pour un prospect Miizy (clé miizy:session:{phone})."""

    def __init__(self, phone: str, redis_client):
        self.phone = phone
        self.redis = redis_client
        self.key = f"miizy:session:{phone}"
        self.data = self._load()

    def _load(self) -> dict:
        try:
            raw = self.redis.get(self.key)
            if raw:
                return json.loads(raw)
        except Exception:
            pass
        return {
            "phone": self.phone,
            "prenom": "",
            "step": "WAITING_NEUF_ANCIEN",
            "branch": None,
            "history": [],
        }

    def save(self):
        try:
            self.redis.setex(self.key, SESSION_TTL, json.dumps(self.data))
        except Exception as e:
            logger.warning(f"[MiizySession] Redis save failed for {self.phone}: {e}")

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
        if msg_id:
            dup_key = f"miizy:msgid:{msg_id}"
            try:
                if self.session.redis.exists(dup_key):
                    logger.info(f"[Miizy] doublon msg_id={msg_id} ignoré")
                    return "", ""
                self.session.redis.setex(dup_key, 120, "1")
            except Exception:
                pass

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
