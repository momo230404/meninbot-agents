#!/usr/bin/env python3
"""Agent IA pour conversations WhatsApp"""
import re
import random
import logging
from typing import Dict, Any

from tools.miizy_api import MiizyAPI
from tools.evolution import EvolutionAPI

logger = logging.getLogger("agent_ia")

class AgentIA:
    """Agent conversationnel Miizy"""
    
    INTENTIONS = {
        "stock": ["stock", "disponible", "bien", "appartement", "maison", "logement"],
        "recherche": ["cherche", "recherche", "trouver", "chercher", "cherche"],
        "visite": ["visite", "rdv", "rendez-vous", "visiter", "voir"],
        "budget": ["budget", "prix", "combien", "coûte", "tarif"],
        "stop": ["stop", "supprime", "désinscrire", "desinscrire"],
        "merci": ["merci", "merci beaucoup", "super", "cool", "ok merci"]
    }

    def __init__(self, config: Dict[str, Any], redis_client):
        self.config = config
        self.redis = redis_client
        self.miizy = MiizyAPI(
            config['vianova']['api_key'],
            config['vianova']['api_base_url']
        )
        self.evolution = EvolutionAPI(
            config['evolution_api']['api_key'],
            config['evolution_api']['base_url'],
            config['evolution_api']['instance_name']
        )

    def process_message(self, phone: str, message: str) -> str:
        """Traite un message entrant"""
        self.redis.add_message(phone, "user", message)
        
        intention = self._detect_intention(message)
        lead_info = self.redis.get_lead_info(phone)
        
        response = self._generate_response(intention, message, lead_info)
        
        if response:
            self.redis.add_message(phone, "assistant", response)
            self.evolution.send_text(phone, response)
        
        return response

    def _detect_intention(self, message: str) -> str:
        msg_lower = message.lower()
        for intent, keywords in self.INTENTIONS.items():
            for kw in keywords:
                if kw in msg_lower:
                    return intent
        return "general"

    def _generate_response(self, intention: str, message: str, lead_info: Dict) -> str:
        if intention == "stop":
            return "Je comprends. Je ne vous enverrai plus de messages."
        
        if intention in ["stock", "recherche"]:
            return self._handle_stock_request(message, lead_info)
        
        if intention == "visite":
            return "Je transmets votre demande de visite à notre équipe. Vos disponibilités ?"
        
        if intention == "budget":
            return "Quelle est votre fourchette de prix ? Je filtrerai en conséquence."
        
        if intention == "merci":
            return "Je vous en prie ! Je reste disponible si besoin."
        
        return "Puis-je vous aider ? Quel type de bien recherchez-vous ?"

    def _handle_stock_request(self, message: str, lead_info: Dict) -> str:
        ville, typologie = self._extract_search_params(message, lead_info)
        
        if not ville or not typologie:
            return "Quelle ville et typologie (T2, T3...) recherchez-vous ?"
        
        # Recherche API Miizy
        biens = self.miizy.search_stock(ville, typologie)
        
        if not biens:
            return f"Je n'ai pas de {typologie} à {ville} actuellement. Puis-je vous notifier ?"
        
        return self.miizy.format_stock_summary(biens, ville, typologie)

    def _extract_search_params(self, message: str, lead_info: Dict) -> tuple:
        villes = ["lyon", "paris", "marseille", "bordeaux", "toulouse", "lille", "nantes", "strasbourg", "nice"]
        typologies = ["t1", "t2", "t3", "t4", "t5", "t6", "studio"]
        
        msg_lower = message.lower()
        
        # Extraction ville
        ville = lead_info.get("ville_recherchee")
        for v in villes:
            if v in msg_lower:
                ville = v.capitalize()
                break
        
        # Extraction typologie
        typo = lead_info.get("typologie_recherchee")
        for t in typologies:
            if t in msg_lower:
                typo = t.upper()
                break
        
        return ville, typo

    def _random_response(self, options: list) -> str:
        return random.choice(options)
