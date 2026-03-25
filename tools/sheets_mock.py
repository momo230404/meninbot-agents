#!/usr/bin/env python3
"""Mock Google Sheets Client pour tester le dashboard"""
import logging
from typing import List, Dict, Any

logger = logging.getLogger("sheets_mock")

class MockGoogleSheetsClient:
    """Simule Google Sheets pour la démo"""
    
    def __init__(self, credentials_file: str = None, sheets_id: str = None):
        logger.info("📊 Utilisant Mock Google Sheets")
        # Données simulées
        self.mock_leads = [
            {
                "row_num": 2,
                "nom": "Dupont",
                "prenom": "Jean",
                "telephone": "+33612345678",
                "ville": "Paris",
                "etat": "Envoyé",
                "date_envoi": "2026-03-14"
            },
            {
                "row_num": 3,
                "nom": "Martin",
                "prenom": "Marie",
                "telephone": "+33687654321",
                "ville": "Lyon",
                "etat": "En cours",
                "date_envoi": "2026-03-13"
            },
            {
                "row_num": 4,
                "nom": "Bernard",
                "prenom": "Pierre",
                "telephone": "+33698765432",
                "ville": "Marseille",
                "etat": "RDV proposé",
                "date_envoi": "2026-03-12"
            },
            {
                "row_num": 5,
                "nom": "Lefevre",
                "prenom": "Sophie",
                "telephone": "+33612987654",
                "ville": "Toulouse",
                "etat": "RDV confirmé",
                "date_envoi": "2026-03-11"
            },
            {
                "row_num": 6,
                "nom": "Garcia",
                "prenom": "Carlos",
                "telephone": "+33634567890",
                "ville": "Bordeaux",
                "etat": "Clos",
                "date_envoi": "2026-03-10"
            }
        ]
    
    def get_all_leads(self, sheet_name: str = "Campagnes") -> List[Dict[str, Any]]:
        """Récupère tous les leads"""
        logger.info(f"📋 Récupération leads depuis {sheet_name}")
        return self.mock_leads
    
    def get_leads_for_campaign(self, sheet_name: str = "Campagnes", status_col: str = "K") -> List[Dict[str, Any]]:
        """Récupère les leads à contacter"""
        return [l for l in self.mock_leads if l.get("etat", "").strip() == "" or l.get("etat") == "À contacter"]
    
    def update_status(self, row_num: int, status: str, sheet_name: str = "Campagnes", status_col: str = "K"):
        """Mets à jour le statut d'une ligne"""
        logger.info(f"✏️  Mise à jour ligne {row_num}: {status}")
        for lead in self.mock_leads:
            if lead["row_num"] == row_num:
                lead["etat"] = status
                break
    
    def append_row(self, values: list, sheet_name: str = "Campagnes"):
        """Ajoute une ligne"""
        logger.info(f"➕ Ajout nouvelle ligne")
        pass
