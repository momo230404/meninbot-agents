#!/usr/bin/env python3
"""
Agent IA Vianova V2 - Cerveau conversationnel amélioré
+ Rapide, + Naturel, + Context-aware
"""
import json
import random
import re
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Tuple, Optional

from conversation_memory import ConversationMemory
from tools.vianova_api import VianovaAPI, get_stock
from tools.evolution import send_conversation_messages, mark_as_read
from tools.calendar_api import GoogleCalendarAPI

CONFIG = json.load(open(Path(__file__).parent / "config.json"))
VIANOVA_API = VianovaAPI()
CALENDAR_API = GoogleCalendarAPI()

# ============ RÉPONSES NATURELLES VARIÉES ============

ACCEPTATIONS_RDV = [
    "Avec plaisir ! Pour vous présenter nos disponibilités, un créneau cette semaine vous irait ?",
    "Parfait ! Je peux vous appeler pour affiner vos critères ? Quand seriez-vous disposé ?",
    "Excellente idée ! Un appel de 10 minutes pourraît faire le job. Vos disponibilités ?",
    "Je note ! Quel jour vous conviendrait mieux pour un échange ?",
    "Top ! Rien de mieux qu'un appel pour avancer sereinement. Vos dispos ?",
]

REFUS_RDV = [
    "Je comprends, pas de souci ! N'hésitez pas si vous changez d'avis.",
    "Pas de problème, je reste disponible si besoin. Bonne continuation !",
    "D'accord, je prends note. Belle journée à vous !",
]

QUESTIONS_VILLE = [
    "Sur quelle ville ou région vous orientez-vous ?",
    "Vous cherchez dans quel secteur principalement ?",
    "C'est pour quelle ville votre projet ?",
]

QUESTIONS_TYPO = [
    "Vous visez quel type de bien ? (T2, T3, maison...)",
    "Quelle typologie vous intéresse ?",
    "Un appartement, une maison ? Combien de pièces ?",
]

INTROS_STOCK = [
    "Concernant votre recherche,",
    "Du côté de {ville},",
    "Pour {ville},",
    "Du côté immobilier,",
]

CLOSING_INTERESTED = [
    "Pour vous conseiller au mieux, un échange rapide serait top. Un créneau cette semaine ?",
    "Je peux vous présenter les meilleures options en direct. Un appel vous conviendrait ?",
]


class VianovaAgent:
    """Agent conversationnel intelligent pour Vianova"""
    
    def __init__(self, phone_number: str):
        self.memory = ConversationMemory(phone_number)
        self.context = self.memory.data.get("lead_info", {})
        self.stage = self.memory.get_stage()
        self.phone_number = phone_number
        self.initial_message_sent = False
        
        # Charger l'historique pour contexte
        self.history = self.memory.get_context(5)
    
    def set_initial_message_sent(self, status: bool):
        self.initial_message_sent = status
        self.memory.save()
    
    def process_message(self, user_message: str, message_id: str = None) -> Tuple[str, str]:
        """
        Point d'entrée principal - traite le message et répond
        """
        # Anti-duplicate
        if message_id and self.memory.is_duplicate(message_id):
            return "", ""
        
        # Sauvegarde
        self.memory.add_message("user", user_message, message_id)
        user_text = user_message.lower().strip()
        
        # ============ DÉDUCTION INTELLIGENTE ============
        intention = self._analyze_intention(user_text)
        
        # ============ RÉPONSE SELON CONTEXTE ============
        
        # 1. Réponse à la relance initiale
        if self.stage == "initial":
            return self._handle_first_contact(intention, user_text)
        
        # 2. Prospect cherche des infos sur le stock
        if intention == "demande_stock" or "ville" in user_text:
            return self._handle_stock_request(user_text)
        
        # 3. Conversation RDV en cours
        if self.stage in ["rdv_proposed", "asking_email", "asking_creneau"]:
            return self._handle_rdv_conversation(intention, user_text)
        
        # 4. Prospect veut changer ville/typologie
        if intention == "nouvelle_ville" or intention == "nouveau_critere":
            return self._handle_new_search(user_text)
        
        # 5. Réponses simples oui/non
        if intention == "positif_simple":
            return self._handle_positive_simple()
        
        if intention == "negatif_simple":
            return self._handle_negative_simple(user_text)
        
        # Fallback intelligent
        return self._handle_intelligent_fallback(user_text, intention)
    
    def _analyze_intention(self, text: str) -> str:
        """
        Analyse intelligente de l'intention utilisateur
        """
        text_lower = text.lower()
        
        # Intentions positives (court ou long)
        if any(word in text_lower for word in ["oui", "yes", "ok", "d'accord", "carrément", "bien sûr", 
                                                  "volontiers", "pourquoi pas", "ça marche", "top", 
                                                  "parfait", "excellent", "intéressé", "je veux bien"]):
            return "positif_simple"
        
        # Intentions négatives
        if any(word in text_lower for word in ["non", "no", "pas", "j'ai trouvé", "plus besoin", 
                                                  "annulé", "désisté", "pas le moment", "pas pour moi"]):
            return "negatif_simple"
        
        # Demande sur stock/disponibilité
        if any(word in text_lower for word in ["disponible", "stock", "programme", "logement", 
                                                  "appartement", "maison", "t2", "t3", "t4", "prix", 
                                                  "budget", "combien", "il reste quoi"]):
            return "demande_stock"
        
        # Mention de nouvelle ville
        if any(word in text_lower for word in ["cherche à", "maintenant c'est", "plutôt", "change",  
                                                  "autre ville", "nouveau", "autre secteur"]):
            return "nouvelle_ville"
        
        # Nouveaux critères
        if any(word in text_lower for word in ["critères", "typologie", "pièces", "surface", 
                                                  "budget", "prix", "étage", "balcon", "terrasse"]):
            return "nouveau_critere"
        
        # Acceptation RDV
        if any(phrase in text_lower for phrase in ["quand", "créneau", "disponible", "dispo", 
                                                       "je suis dispo", "ça me va", "allez-y", 
                                                       "appel", "visio", "rdv", "rendez-vous"]):
            if self.stage in ["rdv_proposed", "stock_annonce"]:
                return "accepte_rdv"
        
        # Refus RDV
        if any(phrase in text_lower for phrase in ["pas besoin", "mail suffit", "juste des infos", 
                                                       "pas le temps", "pas pour le moment"]):
            return "refuse_rdv"
        
        return "inconnu"
    
    def _handle_first_contact(self, intention: str, user_text: str) -> Tuple[str, str]:
        """Gère la première réponse après relance"""
        
        if intention in ["positif_simple", "accepte_rdv", "demande_stock"]:
            # Prospect intéressé - on donne le stock et on propose RDV
            city = self.context.get("ville", "")
            typo = self.context.get("typologie", "")
            
            if not city:
                # On demande la ville d'abord
                self.memory.set_stage("asking_city")
                return random.choice(QUESTIONS_VILLE), ""
            
            # On donne le stock
            stock, msg = get_stock(city, typo)
            self