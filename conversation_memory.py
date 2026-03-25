#!/usr/bin/env python3
"""
Gestion mémoire conversationnelle - Remplace Redis
Stockage simple en JSON par numéro de téléphone
"""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

DATA_DIR = Path(__file__).parent / "conversations"
DATA_DIR.mkdir(exist_ok=True)


class ConversationMemory:
    """Mémoire persistante par conversation WhatsApp"""
    
    def __init__(self, phone_number: str):
        self.phone = self._normalize_phone(phone_number)
        self.file_path = DATA_DIR / f"{self.phone}.json"
        self.data = self._load()
    
    def _normalize_phone(self, phone: str) -> str:
        """Normalise le numéro : enlève @, +, espaces — toujours en format chiffres"""
        p = phone.replace('@s.whatsapp.net', '').replace('@c.us', '').replace('@lid', '')
        p = p.strip().replace('+', '').replace(' ', '').replace('-', '')
        if p.startswith('0') and len(p) == 10:
            p = '33' + p[1:]
        return p
    
    def _load(self) -> dict:
        """Charge la conversation existante"""
        if self.file_path.exists():
            with open(self.file_path, 'r') as f:
                return json.load(f)
        return {
            "phone": self.phone,
            "created_at": datetime.now().isoformat(),
            "last_interaction": None,
            "messages": [],
            "lead_info": {},
            "stage": "initial",  # initial, qualification, rdv_propose, rdv_confirme, clos
            "asked_creneaux": False,
            "rdv_created": False
        }
    
    def save(self):
        """Sauvegarde la conversation"""
        self.data["last_interaction"] = datetime.now().isoformat()
        with open(self.file_path, 'w') as f:
            json.dump(self.data, f, indent=2, default=str)
    
    def add_message(self, role: str, content: str, message_id: str = None):
        """Ajoute un message à l'historique"""
        msg = {
            "role": role,  # 'user' ou 'assistant'
            "content": content,
            "timestamp": datetime.now().isoformat(),
            "message_id": message_id
        }
        self.data["messages"].append(msg)
        
        # Garde uniquement les 20 derniers messages (fenêtre de contexte)
        if len(self.data["messages"]) > 20:
            self.data["messages"] = self.data["messages"][-20:]
        
        self.save()
    
    def is_duplicate(self, message_id: str) -> bool:
        """Vérifie si un message a déjà été traité"""
        if not message_id:
            return False
        return any(m.get("message_id") == message_id for m in self.data["messages"])
    
    def get_context(self, max_messages: int = 10) -> list:
        """Récupère l'historique pour le contexte IA"""
        return self.data["messages"][-max_messages:]
    
    def update_lead_info(self, **kwargs):
        """Met à jour les infos du prospect"""
        self.data["lead_info"].update(kwargs)
        self.save()
    
    def set_stage(self, stage: str):
        """Met à jour l'étape de la conversation"""
        self.data["stage"] = stage
        self.save()
    
    def get_stage(self) -> str:
        """Récupère l'étape actuelle"""
        return self.data.get("stage", "initial")
    
    def is_recent(self, minutes: int = 30) -> bool:
        """Vérifie si la conversation est récente"""
        last = self.data.get("last_interaction")
        if not last:
            return False
        last_dt = datetime.fromisoformat(last)
        return datetime.now() - last_dt < timedelta(minutes=minutes)


def cleanup_old_conversations(days: int = 30):
    """Nettoie les conversations anciennes"""
    cutoff = datetime.now() - timedelta(days=days)
    for file in DATA_DIR.glob("*.json"):
        try:
            with open(file, 'r') as f:
                data = json.load(f)
            last = data.get("last_interaction") or data.get("created_at")
            if last:
                last_dt = datetime.fromisoformat(last)
                if last_dt < cutoff:
                    file.unlink()
        except Exception:
            pass


if __name__ == "__main__":
    # Test
    mem = ConversationMemory("33612345678@s.whatsapp.net")
    print(f"Stage: {mem.get_stage()}")
    mem.add_message("user", "Bonjour, je cherche un appartement", "msg_123")
    print(f"Messages: {len(mem.data['messages'])}")
