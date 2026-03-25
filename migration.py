#!/usr/bin/env python3
"""Script de migration: Google Sheets → Redis + JSON"""
import json
import logging
import sys
from datetime import datetime
from typing import Dict, List, Any
import os

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("migration")

def load_config(config_file: str = 'config.json') -> Dict[str, Any]:
    """Charge la configuration"""
    if not os.path.exists(config_file):
        logger.error(f"❌ Fichier config {config_file} non trouvé")
        return {}
    
    with open(config_file, 'r') as f:
        return json.load(f)

def migrate_from_sheets(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Charge les leads depuis Google Sheets"""
    logger.info("🔄 Chargement des leads depuis Google Sheets...")
    
    try:
        from tools.sheets import GoogleSheetsClient
        
        sheets_client = GoogleSheetsClient(
            config['google']['credentials_file'],
            config['google']['sheets_id']
        )
        
        sheet_name = config['google'].get('campaign_sheet', 'Contacts')
        leads = sheets_client.get_leads_for_campaign(sheet_name)
        
        logger.info(f"✅ {len(leads)} leads chargés depuis Google Sheets")
        
        # Transformer les données Sheets en format leads
        transformed_leads = []
        for lead in leads:
            phone = lead.get('telephone', '').replace('+', '').replace(' ', '')
            
            if not phone:
                logger.warning(f"⚠️  Lead sans téléphone ignoré: {lead.get('nom', '')}")
                continue
            
            transformed_lead = {
                'phone': phone,
                'nom': lead.get('nom', ''),
                'prenom': lead.get('prenom', ''),
                'ville': lead.get('ville', ''),
                'typing': lead.get('typing', ''),
                'budget': lead.get('budget', ''),
                'source': 'google_sheets',
                'state': lead.get('etat', 'initial'),
                'ai_enabled': True,
                'created_at': lead.get('created_at', datetime.now().isoformat()),
                'updated_at': datetime.now().isoformat(),
                'custom_fields': {
                    'row_num': lead.get('row_num'),
                    'original_etat': lead.get('etat', '')
                }
            }
            
            transformed_leads.append(transformed_lead)
        
        logger.info(f"🔄 {len(transformed_leads)} leads transformés")
        return transformed_leads
    
    except ImportError:
        logger.warning("⚠️  GoogleSheetsClient non disponible - utilisant données vides")
        return []
    except Exception as e:
        logger.error(f"❌ Erreur chargement Google Sheets: {e}")
        return []

def migrate_to_redis(leads: List[Dict[str, Any]], redis_client) -> bool:
    """Migre les leads vers Redis"""
    logger.info(f"🚀 Migration de {len(leads)} leads vers Redis...")
    
    try:
        from leads_manager import LeadsManager
        
        leads_manager = LeadsManager(redis_client)
        
        for i, lead in enumerate(leads):
            try:
                leads_manager.add_lead(lead)
                if (i + 1) % 10 == 0:
                    logger.info(f"   {i + 1}/{len(leads)} leads migrés...")
            except Exception as e:
                logger.error(f"❌ Erreur migration lead {lead.get('phone')}: {e}")
        
        logger.info(f"✅ {len(leads)} leads migrés vers Redis")
        return True
    
    except Exception as e:
        logger.error(f"❌ Erreur migration: {e}")
        return False

def run_migration(config_file: str = 'config.json') -> bool:
    """Exécute la migration complète"""
    logger.info("=" * 60)
    logger.info("🔄 DÉBUT MIGRATION: Google Sheets → Redis + JSON")
    logger.info("=" * 60)
    
    # Charger config
    config = load_config(config_file)
    if not config:
        return False
    
    # Initialiser Redis
    try:
        from redis_client import RedisClient
        redis_client = RedisClient(config['redis']['url'])
        logger.info("✅ Redis connecté")
    except Exception as e:
        logger.error(f"❌ Erreur connexion Redis: {e}")
        return False
    
    # Charger les leads depuis Google Sheets
    leads = migrate_from_sheets(config)
    
    # Migrer vers Redis
    if not migrate_to_redis(leads, redis_client):
        return False
    
    # Vérifier la persistance JSON
    try:
        from leads_manager import LeadsManager
        leads_manager = LeadsManager(redis_client, config.get('leads_json_file', 'leads.json'))
        
        # Sync vers JSON
        leads_manager._sync_to_json()
        logger.info(f"💾 Persistance JSON synchronisée: {config.get('leads_json_file', 'leads.json')}")
    except Exception as e:
        logger.error(f"⚠️  Erreur sync JSON: {e}")
    
    logger.info("=" * 60)
    logger.info("✅ MIGRATION COMPLÈTE")
    logger.info("=" * 60)
    
    return True

if __name__ == '__main__':
    success = run_migration()
    sys.exit(0 if success else 1)
