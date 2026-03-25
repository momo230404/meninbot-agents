#!/usr/bin/env python3
"""Module API Evolution WhatsApp"""
import requests
import time
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger("evolution")

class EvolutionAPI:
    """Client API Evolution pour envoi WhatsApp"""
    
    def __init__(self, api_key: str, base_url: str, instance_name: str):
        self.api_key = api_key
        self.base_url = base_url
        self.instance_name = instance_name
        self.headers = {
            "apikey": api_key,
            "Content-Type": "application/json"
        }
    
    def send_text(self, phone: str, message: str, delay: int = 0) -> Dict[str, Any]:
        """Envoie un message texte WhatsApp avec simulation typing."""
        phone_clean = self._format_phone(phone)

        # Délai typing = ~60ms par caractère, entre 3s et 12s
        typing_delay_ms = min(max(len(message) * 60, 3000), 12000)

        payload = {
            "number": phone_clean,
            "text": message,
            "options": {
                "delay": typing_delay_ms,
                "presence": "composing"
            }
        }
        
        try:
            url = f"{self.base_url}/message/sendText/{self.instance_name}"
            response = requests.post(url, headers=self.headers, json=payload, timeout=45)
            if response.status_code >= 400:
                response.raise_for_status()
            result = response.json()
            
            if result.get("key", {}).get("id") or result.get("status") == "success":
                return {"success": True, "messageId": result.get("key", {}).get("id")}
            elif "not_in_whatsapp" in str(result):
                return {"success": False, "error": "pas_sur_whatsapp"}
            else:
                return {"success": False, "error": result}
                
        except Exception as e:
            logger.error(f"Erreur envoi message: {e}")
            return {"success": False, "error": str(e)}
    
    def _format_phone(self, phone: str) -> str:
        """Formate le numéro de téléphone"""
        phone = phone.strip().replace(" ", "").replace("-", "").replace(".", "")
        if phone.startswith("0"):
            phone = "+33" + phone[1:]
        elif phone.startswith("33") and not phone.startswith("+"):
            phone = "+" + phone
        elif not phone.startswith("+"):
            phone = "+33" + phone
        return phone
