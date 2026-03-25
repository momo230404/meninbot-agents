#!/usr/bin/env python3
"""
Agent Vianova V3 - Workflow Miro Exact
Daniel, conseiller immobilier chez Vianova
"""
import json
import random
import re
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Tuple, Optional

from conversation_memory import ConversationMemory
from tools.vianova_api import get_stock
from tools.evolution import send_conversation_messages, mark_as_read
from tools.calendar_api import GoogleCalendarAPI, calendar_api

CONFIG = json.load(open(Path(__file__).parent / "config.json"))

# ============ IDENTITÉ & PERSONNALITÉ ============
IDENTITE = """Tu es Daniel, conseiller immobilier chez Vianova.
Tu contactes des prospects via WhatsApp pour faire le point sur leur recherche immobilière.
Tu es chaleureux, professionnel, et jamais insistant.
Tu ne vends pas — tu conseilles et tu proposes.
Tu vouvoies toujours.
Tu ne mentionnes jamais que tu es un bot ou une IA."""

# ============ FORMULATIONS VARIÉES RDV ============
FORMULATIONS_RDV = [
    "Pour vous conseiller valablement et affiner vos critères, je vous propose un rendez-vous téléphonique ou visio ?",
    "Pour aller plus loin et vous présenter ce qui correspond vraiment à votre projet, un appel ou visio vous conviendrait ?",
    "Pour affiner vos critères et vous conseiller au mieux, je vous suggère un court échange téléphonique ou en visio. Seriez-vous disponible prochainement ?",
]

# ============ STAGES DE CONVERSATION ============
# initial -> relance_envoyee -> attente_reponse -> [branche_A_oui | branche_B_non]
# branche_A: stock_annonce -> rdv_propose -> [email_demande | creneaux_proposes | rdv_confirme]
# branche_B: asking_found -> [found | not_found | new_criteria]


class VianovaAgentV3:
    """Agent conversationnel Daniel - Workflow Miro exact"""
    
    def __init__(self, phone_number: str):
        self.memory = ConversationMemory(phone_number)
        self.context = self.memory.data.get("lead_info", {})
        self.stage = self.memory.get_stage()
        self.phone = phone_number
        self.prenom = self.context.get("prenom", "")
        self.ville = self.context.get("ville", "")
        self.typologie = self.context.get("typologie", "")
    
    def set_relance_sent(self, date_dernier_echange: str = "quelques semaines"):
        """Marque que la relance initiale a été envoyée"""
        self.memory.update_lead_info(
            date_dernier_echange=date_dernier_echange,
            relance_envoyee=True
        )
        self.memory.set_stage("relance_envoyee")
    
    def send_opening_message(self) -> Tuple[str, str]:
        """Génère le message d'ouverture personnalisé"""
        prenom = self.prenom or ""
        ville = self.ville or "votre ville"
        typo = self.typologie or "logement"
        date_echange = self.context.get("date_dernier_echange", "ces derniers temps")
        
        # Variantes d'emoji
        emojis = ["🌟", "👋", "✨", ""]
        emoji = random.choice(emojis)
        
        message = f"Bonjour{prenom and ' ' + prenom or ''}, c'est Daniel de Vianova{emoji and ' ' + emoji or ''}\n\n"
        message += f"Nous avions échangé ensemble {date_echange} au sujet de votre recherche — "
        message += f"je voulais vous partager mon numéro professionnel et en profiter pour faire le point avec vous.\n\n"
        message += f"Êtes-vous toujours en recherche d'un {typo} sur {ville} ?"
        
        return message, ""
    
    def process_message(self, user_message: str, message_id: str = None) -> Tuple[str, str]:
        """Point d'entrée principal du workflow"""
        # Anti-duplicate
        if message_id and self.memory.is_duplicate(message_id):
            return "", ""
        
        # Sauvegarde
        self.memory.add_message("user", user_message, message_id)
        
        user_lower = user_message.lower().strip()
        
        # ============ BRANCHE A — Prospect répond OUI ============
        if self._is_positive_response(user_lower):
            return self._branche_A_oui(user_message)
        
        # ============ BRANCHE B — Prospect répond NON ============
        if self._is_negative_response(user_lower):
            return self._branche_B_non(user_message)
        
        # ============ FALLOUT — Message incompris ou silence ============
        return self._handle_fallback(user_message)
    
    # ============ DÉTECTIONS INTELLIGENTES ============
    
    def _is_positive_response(self, text: str) -> bool:
        """Détecte réponses positives"""
        text = text.lower().strip()
        positives = [
            "oui", "yes", "ouais", "yep", "daccord", "d'accord", "ok", "top",
            "carrément", "carrément", "bien sûr", "volontiers", "pourquoi pas",
            "ça marche", "super", "parfait", "excellent", "intéressé",
            "toujours", "je cherche", "tout à fait", "avec plaisir"
        ]
        return any(p in text for p in positives)
    
    def _is_negative_response(self, text: str) -> bool:
        """Détecte réponses négatives ou refus"""
        text = text.lower().strip()
        negatives = [
            "non", "no", "nop", "pas besoin", "j'ai trouvé", "trouvé",
            "pas le moment", "pas pour moi", "non merci", "plus besoin",
            "déjà fait", "annulé", "désisté", "plus intéressé",
            "pas pour le moment", "ça va", "ensemble", "pas le temps"
        ]
        return any(n in text for n in negatives)
    
    def _contains_email(self, text: str) -> Optional[str]:
        """Extrait l'email s'il y en a un"""
        match = re.search(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", text)
        return match.group(0) if match else None
    
    def _extract_city(self, text: str) -> Optional[str]:
        """Extrait une ville du message"""
        # Patterns courants
        patterns = [
            r"(?:sur|à|a|vers)\s+([A-Z][a-zA-Z\s-]+)",
            r"([A-Z][a-zA-Z\s-]+)(?:\s+maintenant|\s+plutôt|")",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(1).strip()
        return None
    
    # ============ BRANCHE A — Prospect OUI ============
    
    def _branche_A_oui(self, user_message: str) -> Tuple[str, str]:
        """Workflow Branche A: prospect intéressé"""
        
        # ÉTAPE A1 — Annoncer le stock
        ville = self.ville
        typo = self.typologie
        
        if not ville:
            self.memory.set_stage("asking_city")
            return "Parfait ! Pourriez-vous me rappeler sur quelle ville vous souhaitez chercher ?", ""
        
        # Appel API STOCK (jamais inventé)
        stock_data, stock_message = get_stock(ville, typo)
        
        # Si pas de stock, on le dit honnêtement
        if stock_data.get("total_lots", 0) == 0:
            msg = f"À {ville}, nous n'avons malheureusement pas de {typo} disponible actuellement.\n\n"
            msg += "Je peux vous proposer d'autres typologies ou d'autres secteurs ?"
            self.memory.set_stage("asking_alternatives")
            return msg, ""
        
        # Annonce du stock réel
        self.memory.set_stage("stock_annonce")
        self.memory.update_lead_info(stock_data=stock_data)
        
        # ÉTAPE A2 — Proposer RDV
        rdv_formulation = random.choice(FORMULATIONS_RDV)
        self.memory.set_stage("rdv_propose")
        
        return stock_message, rdv_formulation
    
    def _handle_rdv_acceptance(self, user_message: str) -> Tuple[str, str]:
        """Prospect accepte le RDV"""
        self.memory.set_stage("asking