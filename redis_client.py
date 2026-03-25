#!/usr/bin/env python3
"""Client Redis avec fallback en mémoire"""
import json
import redis as redis_lib
from typing import Optional, Dict, Any
import logging
import time
from datetime import datetime, timedelta

logger = logging.getLogger("redis_client")

class MockRedisClient:
    """Client Redis simulé en mémoire (fallback)"""
    
    def __init__(self):
        self.store = {}
        self.expiry = {}
        logger.info("📦 Utilisant stockage en mémoire (pas de Redis)")
    
    def get(self, key: str) -> Optional[str]:
        """Récupère une valeur"""
        # Vérifier expiration
        if key in self.expiry and self.expiry[key] < datetime.now():
            del self.store[key]
            del self.expiry[key]
            return None
        return self.store.get(key)
    
    def set(self, key: str, value: str):
        """Défini une valeur"""
        self.store[key] = value
    
    def setex(self, key: str, seconds: int, value: str):
        """Défini une valeur avec expiration"""
        self.store[key] = value
        self.expiry[key] = datetime.now() + timedelta(seconds=seconds)
    
    def exists(self, key: str) -> int:
        """Vérifie l'existence d'une clé"""
        if key in self.expiry and self.expiry[key] < datetime.now():
            del self.store[key]
            del self.expiry[key]
            return 0
        return 1 if key in self.store else 0
    
    def delete(self, key: str) -> int:
        """Supprime une clé"""
        if key in self.store:
            del self.store[key]
            if key in self.expiry:
                del self.expiry[key]
            return 1
        return 0
    
    def keys(self, pattern: str) -> list:
        """Retourne les clés correspondant au pattern"""
        import fnmatch
        return [k for k in self.store.keys() if fnmatch.fnmatch(k, pattern)]
    
    def ping(self):
        """Ping"""
        return True
    
    def close(self):
        """Ferme la connexion (no-op)"""
        pass


class RedisClient:
    """Client Redis avec fallback en mémoire"""
    
    def __init__(self, redis_url: str):
        self.redis_available = False
        self.client = None
        
        try:
            self.client = redis_lib.from_url(redis_url, decode_responses=True, socket_timeout=5)
            self.client.ping()
            self.redis_available = True
            logger.info("✅ Redis connecté")
        except Exception as e:
            logger.warning(f"⚠️  Redis non disponible: {e}")
            self.client = MockRedisClient()
    
    def get_conversation(self, phone: str) -> Dict[str, Any]:
        """Récupère l'historique de conversation"""
        key = f"conv:{phone}"
        data = self.client.get(key)
        if data:
            return json.loads(data)
        return {
            "messages": [],
            "last_interaction": None,
            "lead_info": {},
            "state": "new"
        }
    
    def save_conversation(self, phone: str, conversation: Dict[str, Any]):
        """Sauvegarde l'historique de conversation"""
        key = f"conv:{phone}"
        self.client.setex(key, 7 * 24 * 3600, json.dumps(conversation))
    
    def add_message(self, phone: str, role: str, content: str):
        """Ajoute un message à la conversation"""
        conv = self.get_conversation(phone)
        conv["messages"].append({
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat()
        })
        conv["last_interaction"] = time.time()
        self.save_conversation(phone, conv)
    
    def set_lead_info(self, phone: str, info: Dict[str, Any]):
        """Met à jour les infos du lead"""
        conv = self.get_conversation(phone)
        conv["lead_info"].update(info)
        self.save_conversation(phone, conv)
    
    def get_lead_info(self, phone: str) -> Dict[str, Any]:
        """Récupère les infos du lead"""
        conv = self.get_conversation(phone)
        return conv.get("lead_info", {})
    
    def get_messages(self, phone: str) -> list:
        """Récupère les messages d'une conversation"""
        conv = self.get_conversation(phone)
        return conv.get("messages", [])
    
    def delete_lead(self, phone: str) -> bool:
        """Supprime un lead (supprime la conversation associée)"""
        key = f"conv:{phone}"
        result = self.client.delete(key)
        return bool(result)
    
    def get_campaign_status(self, campaign_id: str) -> Optional[Dict[str, Any]]:
        """Récupère le statut d'une campagne"""
        key = f"campaign:{campaign_id}"
        data = self.client.get(key)
        if data:
            return json.loads(data)
        return None
    
    def set_campaign_status(self, campaign_id: str, status: Dict[str, Any]):
        """Met à jour le statut d'une campagne"""
        key = f"campaign:{campaign_id}"
        self.client.setex(key, 30 * 24 * 3600, json.dumps(status))
    
    def is_duplicate(self, phone: str, msg_id: str, window_sec: int = 60) -> bool:
        """Vérifie si un message est en doublon (évite bug n8n)"""
        key = f"msg:{phone}:{msg_id}"
        exists = self.client.exists(key)
        if not exists:
            self.client.setex(key, window_sec, "1")
        return bool(exists)
    
    def close(self):
        """Ferme la connexion"""
        self.client.close()
