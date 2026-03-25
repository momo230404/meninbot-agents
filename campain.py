#!/usr/bin/env python3
"""Lanceur de campagnes WhatsApp depuis Google Sheets"""
import json
import time
import random
import logging
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tools.sheets import GoogleSheetsClient
from tools.evolution import EvolutionAPI
from tools.miizy_api import MiizyAPI

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('logs/campaign.log')
    ]
)
logger = logging.getLogger(__name__)


class CampaignManager:
    """Gestionnaire de campagnes WhatsApp"""
    
    STATUSES = {
        "SENT": "Envoyé",
        "WHATSAPP_ERROR": "Pas sur WhatsApp",
        "SEARCHING": "Toujours en recherche",
        "FOUND": "Bien déjà trouvé"
    }

    def __init__(self, config):
        self.config = config
        self.sheets = GoogleSheetsClient(
            config['google']['credentials_file'],
            config['google']['sheets_id']
        )
        self.evolution = EvolutionAPI(
            config['evolution_api']['api_key'],
            config['evolution_api']['base_url'],
            config['evolution_api']['instance_name']
        )
        self.miizy = MiizyAPI(
            config['vianova']['api_key'],
            config['vianova']['api_base_url']
        )
        self.batch_size = config['campaign']['batch_size']
        self.delay_range = config['campaign']['delay_between_messages']

    def run_campaign(self, dry_run: bool = False):
        """Lance une campagne de messages"""
        logger.info("Démarrage campagne...")
        
        sheet_name = self.config['google'].get('campaign_sheet', 'Campagnes')
        status_col = self.config['google'].get('status_column', 'K')
        
        leads = self.sheets.get_leads_for_campaign(sheet_name, status_col)
        
        if not leads:
            logger.info("Aucun lead à contacter")
            return
        
        logger.info(f"{len(leads)} leads à contacter")
        
        sent_count = 0
        error_count = 0
        
        for i, lead in enumerate(leads[:self.batch_size], 1):
            logger.info(f"[{i}] {lead.get('prenom', '')} {lead.get('nom', '')}")
            
            message = self._generate_message(lead)
            
            if dry_run:
                logger.info(f"[DRY RUN] {message[:80]}...")
                continue
            
            phone = lead.get('telephone', '')
            if not phone:
                logger.warning("Pas de téléphone")
                continue
            
            result = self.evolution.send_text(phone, message)
            
            if result.get('success'):
                logger.info("Envoyé")
                self.sheets.update_status(
                    lead['row_num'],
                    self.STATUSES["SENT"],
                    sheet_name,
                    status_col
                )
                sent_count += 1
            elif result.get('error') == "pas_sur_whatsapp":
                logger.warning("Pas sur WhatsApp")
                self.sheets.update_status(
                    lead['row_num'],
                    self.STATUSES["WHATSAPP_ERROR"],
                    sheet_name,
                    status_col
                )
                error_count += 1
            else:
                logger.error(f"Erreur: {result}")
            
            if i < min(len(leads), self.batch_size):
                delay = random.randint(*self.delay_range)
                time.sleep(delay)
        
        logger.info(f"Campagne terminée: {sent_count} envoyés, {error_count} erreurs")

    def _generate_message(self, lead: dict) -> str:
        """Génère un message personnalisé"""
        civilite = lead.get('civilite', '')
        prenom = lead.get('prenom', '').strip()
        ville = lead.get('ville', '').strip()
        typologie = lead.get('typologie', '').strip()
        
        # Recherche du stock si infos disponibles
        stock_msg = ""
        if ville and typologie:
            try:
                biens = self.miizy.search_stock(ville, typologie)
                stock_msg = self.miizy.format_stock_summary(biens, ville, typologie)
            except Exception as e:
                logger.warning(f"Erreur recherche stock: {e}")
        
        # Templates de messages
        templates = [
            f"Bonjour{civilite} {prenom}, ici Thibault de Miizy. {stock_msg if stock_msg else 'Puis-je vous aider dans votre recherche ?'}",
            f"Bonjour{civilite} {prenom}, Thibault de Miizy. J'ai analysé votre demande. {stock_msg if stock_msg else 'Avez-vous trouvé votre bien ?'}",
            f"Bonjour{civilite} {prenom}, c'est Thibault de Miizy. {stock_msg if stock_msg else 'Je suis à votre disposition pour trouver le bon bien.'}"
        ]
        
        return random.choice(templates)

    def update_status_manual(self, row_nums: list, status: str):
        """Met à jour manuellement des statuts"""
        sheet_name = self.config['google'].get('campaign_sheet', 'Campagnes')
        status_col = self.config['google'].get('status_column', 'K')
        
        for row in row_nums:
            self.sheets.update_status(row, status, sheet_name, status_col)
            logger.info(f"Ligne {row} mise à jour: {status}")


def main():
    """Point d'entrée"""
    with open('config.json', 'r') as f:
        config = json.load(f)
    
    campaign = CampaignManager(config)
    
    if len(sys.argv) > 1:
        if sys.argv[1] == "--dry-run":
            campaign.run_campaign(dry_run=True)
        elif sys.argv[1] == "--status" and len(sys.argv) > 3:
            rows = [int(x) for x in sys.argv[2].split(',')]
            status = sys.argv[3]
            campaign.update_status_manual(rows, status)
        else:
            print("Usage: python campain.py [--dry-run] [--status '1,2,3' 'SEARCHING']")
            sys.exit(1)
    else:
        campaign.run_campaign()


if __name__ == "__main__":
    main()
