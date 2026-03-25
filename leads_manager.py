#!/usr/bin/env python3
"""Gestionnaire des leads - Redis + JSON local sync"""
import json
import logging
from datetime import datetime
from typing import Dict, List, Any, Optional
import os
from redis_client import RedisClient

logger = logging.getLogger("leads_manager")

class LeadsManager:
    """Gère les leads avec Redis comme stockage principal et JSON pour backup/persistance"""
    
    def __init__(self, redis_client: RedisClient, json_file: str = "leads.json", prefix: str = "lead:"):
        """
        Initialise le gestionnaire des leads

        Args:
            redis_client: Instance RedisClient configurée
            json_file: Chemin du fichier JSON local pour persistance
            prefix: Préfixe Redis pour isoler les leads par agent
        """
        self.redis = redis_client
        self.json_file = json_file
        self.leads_prefix = prefix
        
        # Créer le dossier s'il n'existe pas
        os.makedirs(os.path.dirname(json_file) if os.path.dirname(json_file) else '.', exist_ok=True)
        
        logger.info(f"📋 LeadsManager initialisé - Stockage: {json_file}")
    
    def _format_phone(self, phone: str) -> str:
        """Formate et nettoie un numéro de téléphone pour la clé Redis"""
        return phone.replace('+', '').replace(' ', '').replace('-', '')
    
    def _make_lead_key(self, phone: str) -> str:
        """Génère la clé Redis pour un lead"""
        return f"{self.leads_prefix}{self._format_phone(phone)}"
    
    # ==================== CRUD OPERATIONS ====================
    
    def add_lead(self, lead_data: Dict[str, Any]) -> bool:
        """
        Ajoute un nouveau lead
        
        Args:
            lead_data: Dict avec: phone (obligatoire), nom, prenom, ville, typing, budget, etc.
        
        Returns:
            True si succès
        """
        if not lead_data.get('phone'):
            logger.error("❌ Téléphone obligatoire pour ajouter un lead")
            return False
        
        phone = lead_data['phone']
        key = self._make_lead_key(phone)
        
        # Préparer le lead complet
        lead = {
            "phone": phone,
            "telephone": phone,
            "nom": lead_data.get('nom', ''),
            "prenom": lead_data.get('prenom', ''),
            "ville": lead_data.get('ville', ''),
            "typologie": lead_data.get('typologie', ''),
            "typing": lead_data.get('typing', lead_data.get('typologie', '')),
            "budget": lead_data.get('budget', ''),
            "date_dernier_contact": lead_data.get('date_dernier_contact', ''),
            "date_envoi": lead_data.get('date_envoi', ''),
            "etat": lead_data.get('etat', lead_data.get('state', 'initial')),
            "source": lead_data.get('source', 'manual'),
            "state": lead_data.get('etat', lead_data.get('state', 'initial')),
            "ai_enabled": lead_data.get('ai_enabled', True),
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "sent_at": lead_data.get('sent_at'),
            "last_message_at": lead_data.get('last_message_at'),
            "rdv_confirmed_at": lead_data.get('rdv_confirmed_at'),
            "custom_fields": lead_data.get('custom_fields', {})
        }
        
        # Sauvegarder dans Redis
        self.redis.client.set(key, json.dumps(lead))

        # Sync ciblé avec JSON local (sans KEYS scan — fiable sur Upstash)
        self._update_lead_in_json(phone, lead)

        logger.info(f"✅ Lead ajouté: {phone}")
        return True
    
    def get_lead(self, phone: str) -> Optional[Dict[str, Any]]:
        """Récupère un lead par son téléphone (Redis puis fallback JSON)"""
        key = self._make_lead_key(phone)
        data = self.redis.client.get(key)

        if data:
            try:
                return json.loads(data)
            except json.JSONDecodeError:
                logger.error(f"❌ Erreur JSON pour lead: {phone}")

        # Fallback JSON local si Redis indisponible ou lead absent
        phone_clean = phone.lstrip('+')
        for lead in self.load_from_json():
            lphone = (lead.get('phone') or lead.get('telephone') or '').lstrip('+')
            if lphone == phone_clean:
                return lead

        logger.debug(f"⚠️  Lead non trouvé: {phone}")
        return None
    
    def update_lead(self, phone: str, updates: Dict[str, Any]) -> bool:
        """
        Met à jour un lead existant
        
        Args:
            phone: Numéro de téléphone du lead
            updates: Dict avec les champs à mettre à jour
        
        Returns:
            True si succès
        """
        lead = self.get_lead(phone)
        if not lead:
            logger.error(f"❌ Lead non trouvé: {phone}")
            return False

        # Protéger les champs importants : ne jamais écraser une valeur non-vide par une valeur vide
        _PROTECTED = {'ville', 'typologie', 'nom', 'prenom', 'budget', 'source', 'phone', 'telephone'}
        safe_updates = {}
        for k, v in updates.items():
            if k in _PROTECTED and not v and lead.get(k):
                pass  # ignore la mise à jour vide sur un champ rempli
            else:
                safe_updates[k] = v

        lead.update(safe_updates)
        lead['updated_at'] = datetime.now().isoformat()

        # Sauvegarder dans Redis
        key = self._make_lead_key(phone)
        self.redis.client.set(key, json.dumps(lead))

        # Sync ciblé : mettre à jour uniquement ce lead dans le JSON (pas de scan Redis global)
        self._update_lead_in_json(phone, lead)

        logger.info(f"✏️  Lead mis à jour: {phone}")
        return True

    def _update_lead_in_json(self, phone: str, lead: dict) -> bool:
        """Met à jour un seul lead dans le JSON local sans scan Redis global."""
        try:
            existing = self.load_from_json()
            phone_clean = phone.lstrip('+')
            found = False
            for i, l in enumerate(existing):
                lphone = (l.get('phone') or l.get('telephone') or '').lstrip('+')
                if lphone == phone_clean:
                    # Merge : les champs non-vides du JSON existant priment sur les valeurs vides
                    merged = {**l, **lead}
                    for field in _PROTECTED if hasattr(self, '_PROTECTED') else {'ville', 'typologie', 'nom', 'prenom', 'budget'}:
                        if l.get(field) and not lead.get(field):
                            merged[field] = l[field]
                    existing[i] = merged
                    found = True
                    break
            if not found:
                existing.append(lead)
            with open(self.json_file, 'w', encoding='utf-8') as f:
                json.dump({'leads': existing, 'last_sync': datetime.now().isoformat(), 'count': len(existing)}, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            logger.error(f"❌ Erreur update JSON lead {phone}: {e}")
            return False
    
    def delete_lead(self, phone: str) -> bool:
        """Supprime un lead — Redis ET JSON (fonctionne même si Redis est down)."""
        phone_clean = phone.lstrip('+')

        # 1. Supprimer dans Redis (silencieux si Redis KO)
        redis_deleted = False
        try:
            key = self._make_lead_key(phone)
            redis_deleted = bool(self.redis.client.delete(key))
        except Exception:
            pass

        # 2. Supprimer dans le JSON local (source de vérité si Redis KO)
        json_deleted = False
        try:
            existing = self.load_from_json()
            new_list = []
            for l in existing:
                lphone = (l.get('phone') or l.get('telephone') or '').replace('+', '').replace(' ', '').replace('-', '')
                if lphone == phone_clean.replace('+', '').replace(' ', '').replace('-', ''):
                    json_deleted = True
                else:
                    new_list.append(l)
            if json_deleted:
                with open(self.json_file, 'w', encoding='utf-8') as f:
                    json.dump({'leads': new_list, 'last_sync': datetime.now().isoformat(), 'count': len(new_list)}, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"❌ Erreur suppression JSON lead {phone}: {e}")

        deleted = redis_deleted or json_deleted
        if deleted:
            logger.info(f"🗑️  Lead supprimé: {phone} (redis={redis_deleted}, json={json_deleted})")
        else:
            logger.warning(f"⚠️  Lead non trouvé pour suppression: {phone}")
        return deleted
    
    def list_leads(self, filter_state: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Liste tous les leads
        
        Args:
            filter_state: Filtrer par état (optionnel)
        
        Returns:
            Liste des leads
        """
        if hasattr(self.redis.client, 'keys'):
            keys = self.redis.client.keys(f"{self.leads_prefix}*")
        else:
            keys = [k for k in getattr(self.redis.client, 'store', {}).keys() if k.startswith(self.leads_prefix)]

        leads = []
        for key in keys:
            data = self.redis.client.get(key)
            if data:
                try:
                    lead = json.loads(data)
                    if not filter_state or lead.get('state') == filter_state:
                        leads.append(lead)
                except json.JSONDecodeError:
                    logger.error(f"❌ Erreur JSON pour clé: {key}")

        # Fallback JSON si Redis ne renvoie aucun lead (KEYS instable sur Upstash)
        if not leads:
            logger.warning("⚠️  list_leads: Redis vide — fallback JSON local")
            json_leads = self.load_from_json()
            if json_leads:
                leads = [l for l in json_leads if not filter_state or l.get('state') == filter_state]

        return leads
    
    # ==================== STATE MANAGEMENT ====================
    
    def get_state(self, phone: str) -> str:
        """Récupère l'état d'un lead"""
        lead = self.get_lead(phone)
        return lead.get('state', 'initial') if lead else 'initial'
    
    def set_state(self, phone: str, state: str) -> bool:
        """Met à jour l'état d'un lead"""
        return self.update_lead(phone, {
            'state': state,
            'state_updated_at': datetime.now().isoformat()
        })
    
    def toggle_ai(self, phone: str) -> Optional[bool]:
        """Active/désactive l'IA pour un lead"""
        lead = self.get_lead(phone)
        if not lead:
            return None
        
        new_state = not lead.get('ai_enabled', True)
        self.update_lead(phone, {'ai_enabled': new_state})
        return new_state
    
    # ==================== JSON PERSISTENCE ====================
    
    def _sync_to_json(self) -> bool:
        """Synchronise les leads Redis vers JSON local (merge — ne supprime pas les leads absents de Redis)."""
        try:
            # Leads en mémoire JSON (source de référence pour les champs complets)
            existing = {(l.get('phone') or l.get('telephone', '')).lstrip('+'): l for l in self.load_from_json()}
            # Leads Redis (peuvent être partiels si Redis a évicté des clés)
            for lead in self.list_leads():
                phone_clean = (lead.get('phone') or lead.get('telephone', '')).lstrip('+')
                if phone_clean:
                    existing_lead = existing.get(phone_clean, {})
                    # Merge : préserver les champs importants existants si absents dans Redis
                    for field in ('ville', 'typologie', 'nom', 'prenom', 'budget'):
                        if existing_lead.get(field) and not lead.get(field):
                            lead[field] = existing_lead[field]
                    existing[phone_clean] = lead
            merged = list(existing.values())
            with open(self.json_file, 'w', encoding='utf-8') as f:
                json.dump({'leads': merged, 'last_sync': datetime.now().isoformat(), 'count': len(merged)}, f, ensure_ascii=False, indent=2)
            logger.debug(f"💾 Sync JSON: {len(merged)} leads sauvegardés")
            return True
        except Exception as e:
            logger.error(f"❌ Erreur sync JSON: {e}")
            return False
    
    def load_from_json(self) -> List[Dict[str, Any]]:
        """Charge tous les leads depuis le fichier JSON"""
        try:
            if os.path.exists(self.json_file):
                with open(self.json_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    leads = data.get('leads', [])
                    logger.info(f"📥 Chargé {len(leads)} leads depuis JSON")
                    return leads
            else:
                logger.info(f"📄 Fichier JSON non trouvé: {self.json_file}")
                return []
        except Exception as e:
            logger.error(f"❌ Erreur chargement JSON: {e}")
            return []
    
    def save_leads_from_json(self) -> bool:
        """Charge les leads depuis JSON et les injecte dans Redis"""
        leads = self.load_from_json()
        for lead in leads:
            phone = lead.get('phone')
            if phone:
                key = self._make_lead_key(phone)
                self.redis.client.set(key, json.dumps(lead))
        
        return len(leads) > 0
    
    # ==================== EXPORT/IMPORT ====================
    
    def export_to_json_file(self, filepath: str) -> bool:
        """Exporte tous les leads vers un fichier JSON spécifique"""
        try:
            leads = self.list_leads()
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump({
                    'leads': leads,
                    'exported_at': datetime.now().isoformat(),
                    'count': len(leads)
                }, f, ensure_ascii=False, indent=2)
            
            logger.info(f"📤 Export {len(leads)} leads vers {filepath}")
            return True
        except Exception as e:
            logger.error(f"❌ Erreur export: {e}")
            return False
    
    def import_from_json_file(self, filepath: str) -> bool:
        """Importe les leads depuis un fichier JSON spécifique"""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
                leads = data.get('leads', [])
            
            for lead in leads:
                if lead.get('phone'):
                    self.add_lead(lead)
            
            logger.info(f"📥 Import {len(leads)} leads depuis {filepath}")
            return True
        except Exception as e:
            logger.error(f"❌ Erreur import: {e}")
            return False
    
    # ==================== STATISTICS ====================
    
    def get_stats(self) -> Dict[str, Any]:
        """Retourne les statistiques des leads"""
        leads = self.list_leads()
        
        states = {}
        for lead in leads:
            state = lead.get('state', 'initial')
            states[state] = states.get(state, 0) + 1
        
        return {
            'total': len(leads),
            'by_state': states,
            'ai_enabled_count': sum(1 for l in leads if l.get('ai_enabled', True)),
            'updated_at': datetime.now().isoformat()
        }
    
    def get_leads_needing_relance(self, hours: int = 24) -> List[Dict[str, Any]]:
        """Retourne les leads qui ont besoin d'une relance"""
        leads = self.list_leads()
        relance_leads = []
        
        for lead in leads:
            state = lead.get('state', 'initial')
            last_msg = lead.get('last_message_at')
            
            # Ne pas relancer: clos, rdv confirmé, initial
            if state in ['clos', 'rdv_confirme', 'initial']:
                continue
            
            if not last_msg:
                continue
            
            try:
                last_msg_time = datetime.fromisoformat(last_msg)
                hours_since = (datetime.now() - last_msg_time).total_seconds() / 3600
                
                if hours_since > hours:
                    relance_leads.append(lead)
            except:
                pass
        
        return relance_leads
