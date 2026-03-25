#!/usr/bin/env python3
"""
Couche hors-contexte — Agent Vianova
Détection et réponse aux messages qui ne correspondent pas au flux conversationnel.
"""
import re
import logging
from typing import Optional, Tuple
from pathlib import Path as _P
import json as _json

logger = logging.getLogger(__name__)

def _sc_get(key: str) -> str:
    """Charge la réponse depuis agent_scenarios.json"""
    try:
        p = _P(__file__).parent.parent / 'agent_scenarios.json'
        if p.exists():
            responses = _json.loads(p.read_text()).get('scenarios', {}).get(key, {}).get('responses', [])
            if responses:
                return responses[0]
    except Exception:
        pass
    return None

# ── Patterns FAQ (ordre = priorité) ─────────────────────────────────────────
_FAQ_PATTERNS = [
    # Invitation / envoi
    (re.compile(
        r"invit|envoy[eé]|re[çc]u.*mail|mail.*re[çc]u|lien.*meet|meet.*lien|confirmation.*rdv|rdv.*confirm",
        re.I), "invitation"),
    # Identité
    (re.compile(
        r"c'?est qui|vous [eê]tes qui|t'?es qui|vous [eê]tes quoi|qui (?:[eê]tes|es)-?vous"
        r"|qui suis.je|d'?o[uù] venez.vous|vous (me )?conn?aissez",
        re.I), "identity"),
    # Vianova
    (re.compile(
        r"c'?est quoi vianova|vianova c'?est quoi|qu'?est.ce que vianova"
        r"|(?:what|comment).{0,20}vianova|vianova.{0,20}\?",
        re.I), "vianova"),
    # Numéro / contact
    (re.compile(
        r"(?:eu|avoir|trouv[eé]|d'?o[uù]|comment|pourquoi).{0,20}(?:mon\s+)?num[eé]ro"
        r"|num[eé]ro.{0,20}(?:eu|trouv[eé]|d'?o[uù]|comment)"
        r"|comment.{0,10}contact|vous me contactez pourquoi",
        re.I), "numero"),
    # Insultes / agressivité
    (re.compile(
        r"\b(merde|putain|con\b|connard|abruti|idiot|nul\b|incomp[eé]tent"
        r"|arnaque|escroc|enc[ou]l[eé]|va te faire|casse.toi|ferme.la|ta gueule)\b",
        re.I), "insult"),
    # Demande d'arrêt
    (re.compile(
        r"\b(stop\b|arrêtez|laissez.moi|tranquille|plus de message"
        r"|d[eé]sinscri|retirez.moi|pas int[eé]ress[eé]|ne veux? pas|fichier.moi)\b",
        re.I), "stop"),
]

# Mots qui indiquent une vraie question hors-flux
_QUESTION_SIGNALS = re.compile(
    r"^(comment|pourquoi|c'est quoi|qu'est.ce|qui|quand|o[uù]|ça fait quoi|ça sert [aà])",
    re.I
)


def detect_off_context(txt: str, stage: str) -> Optional[str]:
    """
    Retourne la clé FAQ si le message est hors-contexte, None sinon.
    """
    # 1. Patterns FAQ absolus (peu importe le stage)
    for pattern, key in _FAQ_PATTERNS:
        if pattern.search(txt):
            logger.info(f"[off_context] Détecté: {key!r} | stage={stage!r} | msg={txt[:50]!r}")
            return key

    # 2. Question ouverte non attendue dans les stages actifs
    if stage in ("rdv_confirme", "rdv_propose", "attente_email",
                 "attente_creneau", "confirme_creneau"):
        is_question = txt.endswith("?") or _QUESTION_SIGNALS.match(txt)
        if is_question:
            # Exclure les réponses légitimes qui ont "?"
            legit = re.compile(
                r"^(oui|non|ok|d'accord|lequel|laquelle|"
                r"lundi|mardi|mercredi|jeudi|vendredi|premier|deuxi)",
                re.I
            )
            if not legit.match(txt):
                logger.info(f"[off_context] Question ouverte hors-flux | stage={stage!r} | msg={txt[:50]!r}")
                return "generic_question"

    return None


def off_context_response(faq_key: str, txt: str, memory) -> str:
    """
    Retourne la réponse appropriée pour un message hors-contexte.
    """
    lead = memory.data.get("lead_info", {})
    stage = memory.get_stage()

    if faq_key == "invitation":
        email = lead.get("email", "")
        slot = lead.get("creneau_en_attente", "") or (
            lead.get("creneaux_proposes", [""])[-1] if lead.get("creneaux_proposes") else "")
        if stage == "rdv_confirme" and email:
            return (f"Oui, l'invitation a bien été envoyée à {email} ! "
                    f"Vérifiez vos spams si vous ne la voyez pas 📬")
        elif stage == "rdv_confirme":
            return "Je vérifie ça de mon côté et vous reviens très vite !"
        else:
            return "L'invitation sera envoyée dès que votre RDV sera confirmé 👍"

    if faq_key == "identity":
        return _sc_get('identity') or ("Je suis Daniel, conseiller chez Vianova ⚡ — une plateforme spécialisée "
                "dans l'immobilier neuf. Je vous accompagne pour trouver le bien qui "
                "correspond à votre projet !")

    if faq_key == "vianova":
        return _sc_get('vianova') or ("Vianova ⚡ est une plateforme qui connecte les acquéreurs avec les meilleurs "
                "programmes immobiliers neufs en France — plus de 40 000 lots disponibles "
                "partout sur le territoire !")

    if faq_key == "numero":
        return _sc_get('numero') or ("Vous aviez manifesté votre intérêt pour de l'immobilier neuf, c'est dans "
                "ce cadre que je vous contacte. Mon objectif est simplement de vous aider "
                "à trouver le bien qui vous correspond !")

    if faq_key == "insult":
        return _sc_get('insult') or ("Je comprends que vous puissiez être contrarié, et je vous présente mes "
                "excuses si quelque chose vous a déplu. Je reste à votre disposition "
                "si vous souhaitez échanger. 🙏")

    if faq_key == "stop":
        return _sc_get('stop') or ("Bien sûr, je ne vous recontacterai plus. Bonne continuation et n'hésitez "
                "pas à revenir vers nous si besoin un jour ! 🙏")

    if faq_key == "generic_question":
        return ("Je ne suis pas sûr de bien comprendre votre question. "
                "N'hésitez pas à me préciser, je suis là pour vous aider !")

    return "Je n'ai pas bien saisi. Pouvez-vous reformuler ?"


def context_recovery(stage: str, memory) -> str:
    """
    Phrase de reprise naturelle selon l'étape en cours.
    Retourne "" si pas de reprise nécessaire (stage terminal).
    """
    lead = memory.data.get("lead_info", {})
    creneaux = lead.get("creneaux_proposes", [])
    slot_attente = lead.get("creneau_en_attente", "")
    email = lead.get("email", "")

    if stage == "rdv_confirme":
        slot = slot_attente or (creneaux[-1] if creneaux else "")
        if slot:
            return f"En tout cas, votre RDV est bien noté pour le {slot}. À très bientôt ! 😊"
        return "En tout cas, votre RDV est bien noté. À très bientôt ! 😊"

    if stage == "confirme_creneau":
        if slot_attente:
            return f"Pour revenir à notre échange : le {slot_attente} vous convient bien ? (Oui/Non)"
        return "Pour revenir à notre échange, avez-vous fait votre choix ?"

    if stage == "attente_creneau":
        active = creneaux[-3:] if len(creneaux) >= 3 else creneaux
        if active:
            slots_str = "\n".join(f"• {s}" for s in active)
            return f"Pour revenir à notre échange, lequel de ces créneaux vous conviendrait ?\n{slots_str}"
        return "Pour revenir à notre échange, avez-vous une préférence pour le créneau ?"

    if stage == "attente_email":
        return ("Pour revenir à notre échange, pourriez-vous me communiquer votre adresse "
                "email pour l'invitation Google Meet ?")

    if stage == "rdv_propose":
        return ("Pour revenir à votre projet, seriez-vous disponible pour un court échange "
                "téléphonique ou en visio ?")

    if stage in ("waiting_info", "initial", "relance_creneau"):
        return ("Pour revenir à votre recherche, avez-vous des critères particuliers "
                "en tête — une ville ou un type de bien ?")

    return ""


def detect_loop(memory) -> bool:
    """
    Détecte si le même message agent a été envoyé 2 fois consécutives (sans avancement).
    Utilise le champ _last_response stocké dans lead_info.
    """
    lead = memory.data.get("lead_info", {})
    last_r = lead.get("_last_response", "")
    prev_r = lead.get("_prev_response", "")
    return bool(last_r and last_r == prev_r)


def store_response(memory, response: str):
    """
    Mémorise la dernière réponse envoyée pour détecter les boucles.
    Doit être appelé juste avant le return final de process_message.
    """
    lead = memory.data.get("lead_info", {})
    prev = lead.get("_last_response", "")
    memory.update_lead_info(_last_response=response, _prev_response=prev)
