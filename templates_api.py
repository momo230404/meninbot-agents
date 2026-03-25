#!/usr/bin/env python3
"""Gestion des templates de messages"""
import json
from datetime import datetime
from typing import Dict, Any

class MessageTemplates:
    """Gère les templates de messages avec variables"""
    
    # Templates par défaut
    DEFAULT_TEMPLATES = {
        "initial": {
            "name": "Message initial",
            "text": "Bonjour {Prenom},\n\nC'est Daniel de Vianova \U0001f44b\n\nNous avions échangé ensemble le {dernier contact} au sujet de votre recherche — je voulais vous partager mon numéro professionnel et en profiter pour faire le point avec vous.\n\nÊtes-vous toujours en recherche d'un {Typologie} sur {Ville} ?",
            "variables": ["Prenom", "dernier contact", "Typologie", "Ville"],
            "delay_hours": 0
        },
        "relance_24h": {
            "name": "Relance 24h",
            "text": "Bonjour {prenom},\n\nAvez-vous eu du temps pour réfléchir à votre projet immobilier à {ville} ?\n\nJ'ai plusieurs {typologie} disponibles dans votre gamme de prix.",
            "variables": ["prenom", "ville", "typologie"],
            "delay_hours": 24
        },
        "relance_72h": {
            "name": "Relance 72h",
            "text": "Bonjour {prenom},\n\nDernier rappel ! J'ai de nouveaux {typologie} à {ville} qui pourraient vous intéresser.\n\nVous aviez eu un dernier échange le {date_dernier_echange}.\n\nIntéressé pour un échange rapide ?",
            "variables": ["prenom", "ville", "typologie", "date_dernier_echange"],
            "delay_hours": 72
        },
        "custom": {
            "name": "Message personnalisé",
            "text": "Bonjour {prenom},\n\nMessage personnalisé",
            "variables": ["prenom", "ville", "typologie", "budget", "date_dernier_echange"],
            "delay_hours": 0
        }
    }
    
    @staticmethod
    def render(template_key: str, variables: Dict[str, Any], custom_text: str = None) -> str:
        """Rendu un template avec les variables"""
        if custom_text:
            text = custom_text
        else:
            if template_key not in MessageTemplates.DEFAULT_TEMPLATES:
                return "Template non trouvé"
            text = MessageTemplates.DEFAULT_TEMPLATES[template_key]["text"]
        
        # Remplacer les variables
        for key, value in variables.items():
            text = text.replace(f"{{{key}}}", str(value or ""))
        
        return text
    
    @staticmethod
    def get_template(template_key: str) -> Dict[str, Any]:
        """Récupère un template"""
        return MessageTemplates.DEFAULT_TEMPLATES.get(template_key, {})
    
    @staticmethod
    def list_templates() -> Dict[str, Any]:
        """Liste tous les templates"""
        return MessageTemplates.DEFAULT_TEMPLATES
    
    @staticmethod
    def preview(template_key: str, variables: Dict[str, Any] = None) -> str:
        """Prévisualise un template"""
        if variables is None:
            variables = {
                "Prenom": "Mohamed",
                "Ville": "Saint-Denis",
                "Typologie": "T3",
                "dernier contact": "12 mars 2026"
            }
        
        return MessageTemplates.render(template_key, variables)
