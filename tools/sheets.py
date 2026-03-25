#!/usr/bin/env python3
"""Module Google Sheets"""
from google.oauth2 import service_account
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from typing import List, Dict, Any, Optional
import logging

logger = logging.getLogger("sheets")

class GoogleSheetsClient:
    """Client Google Sheets pour campagnes"""
    
    SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
    
    def __init__(self, credentials_file: str, sheet_id: str):
        self.sheet_id = sheet_id
        from google.auth.transport.requests import Request
        import os
        token_file = os.path.join(os.path.dirname(credentials_file), 'token.json')
        self.creds = Credentials.from_authorized_user_file(token_file)
        if self.creds.expired and self.creds.refresh_token:
            self.creds.refresh(Request())
        self.service = build('sheets', 'v4', credentials=self.creds)
    
    def get_all_leads(self, sheet_name: str = "Contacts") -> List[Dict[str, Any]]:
        """Récupère TOUS les leads (même ceux déjà contactés)"""
        try:
            range_name = f"{sheet_name}!A:K"
            result = self.service.spreadsheets().values().get(
                spreadsheetId=self.sheet_id,
                range=range_name
            ).execute()
            
            values = result.get('values', [])
            if not values or len(values) < 2:
                logger.warning("Aucune donnée trouvée dans le sheet")
                return []
            
            headers = values[0]
            leads = []
            
            for i, row in enumerate(values[1:], start=2):
                lead = self._parse_row(row, headers, i)
                if lead.get("telephone"):  # Seulement si téléphone
                    leads.append(lead)
            
            logger.info(f"{len(leads)} leads total trouvés")
            return leads
            
        except Exception as e:
            logger.error(f"Erreur lecture sheet (get_all_leads): {e}")
            return []
    
    def get_leads_for_campaign(self, sheet_name: str = "Contacts", status_col: str = "K") -> List[Dict[str, Any]]:
        """Récupère les leads à contacter (colonne K vide)"""
        try:
            range_name = f"{sheet_name}!A:K"
            result = self.service.spreadsheets().values().get(
                spreadsheetId=self.sheet_id,
                range=range_name
            ).execute()
            
            values = result.get('values', [])
            if not values or len(values) < 2:
                logger.warning("Aucune donnée trouvée dans le sheet")
                return []
            
            headers = values[0]
            leads = []
            
            for i, row in enumerate(values[1:], start=2):
                if len(row) <= 10 or not row[10]:
                    lead = self._parse_row(row, headers, i)
                    leads.append(lead)
            
            logger.info(f"{len(leads)} leads à contacter trouvés")
            return leads
            
        except Exception as e:
            logger.error(f"Erreur lecture sheet: {e}")
            return []
    
    def update_status(self, row_num: int, status: str, sheet_name: str = "Contacts", status_col: str = "K"):
        """Met à jour le statut d'un lead dans la colonne K"""
        try:
            cell = f"{sheet_name}!{status_col}{row_num}"
            body = {"values": [[status]]}
            
            self.service.spreadsheets().values().update(
                spreadsheetId=self.sheet_id,
                range=cell,
                valueInputOption="USER_ENTERED",
                body=body
            ).execute()
            
            logger.info(f"Statut ligne {row_num} mis à jour: {status}")
            return True
            
        except Exception as e:
            logger.error(f"Erreur mise à jour statut ligne {row_num}: {e}")
            return False
    
    def _parse_row(self, row: List[str], headers: List[str], row_num: int) -> Dict[str, Any]:
        """Parse une ligne du sheet"""
        # Mapping: A=Civilite, B=Nom, C=Prenom, D=Telephone, E=Ville, F=Typologie...
        return {
            "civilite": row[0] if len(row) > 0 else "",
            "nom": row[1] if len(row) > 1 else "",
            "prenom": row[2] if len(row) > 2 else "",
            "telephone": self._clean_phone(row[3]) if len(row) > 3 else "",
            "ville": row[4] if len(row) > 4 else "",
            "typologie": row[5] if len(row) > 5 else "",
            "budget": row[6] if len(row) > 6 else "",
            "row_num": row_num
        }
    
    def add_lead(self, sheet_name: str, lead_data: Dict[str, Any]) -> bool:
        """Ajoute un nouveau lead à la feuille"""
        try:
            # Récupérer le nombre de lignes actuelles
            range_name = f"{sheet_name}!A:A"
            result = self.service.spreadsheets().values().get(
                spreadsheetId=self.sheet_id,
                range=range_name
            ).execute()
            
            values = result.get('values', [])
            next_row = len(values) + 1
            
            # Préparer la nouvelle ligne
            new_row = [
                "",  # Civilité
                lead_data.get('nom', ''),
                lead_data.get('prenom', ''),
                lead_data.get('telephone', ''),
                lead_data.get('ville', ''),
                lead_data.get('typing', ''),
                lead_data.get('budget', ''),
                "",  # Colonne vide
                "",  # Colonne vide
                "",  # Colonne vide
                lead_data.get('etat', 'initial')  # État
            ]
            
            cell_range = f"{sheet_name}!A{next_row}:K{next_row}"
            body = {"values": [new_row]}
            
            self.service.spreadsheets().values().update(
                spreadsheetId=self.sheet_id,
                range=cell_range,
                valueInputOption="USER_ENTERED",
                body=body
            ).execute()
            
            logger.info(f"✅ Lead ajouté ligne {next_row}")
            return True
            
        except Exception as e:
            logger.error(f"Erreur ajout lead: {e}")
            return False
    
    def update_lead(self, sheet_name: str, phone: str, lead_data: Dict[str, Any]) -> bool:
        """Met à jour un lead existant"""
        try:
            # Trouver la ligne avec ce téléphone
            range_name = f"{sheet_name}!A:K"
            result = self.service.spreadsheets().values().get(
                spreadsheetId=self.sheet_id,
                range=range_name
            ).execute()
            
            values = result.get('values', [])
            row_num = None
            
            for i, row in enumerate(values[1:], start=2):
                if len(row) > 3 and self._clean_phone(row[3]) == phone:
                    row_num = i
                    break
            
            if not row_num:
                logger.warning(f"Lead {phone} non trouvé")
                return False
            
            # Mettre à jour la ligne
            updated_row = [
                "",
                lead_data.get('nom', ''),
                lead_data.get('prenom', ''),
                lead_data.get('telephone', ''),
                lead_data.get('ville', ''),
                lead_data.get('typing', ''),
                lead_data.get('budget', ''),
                "",
                "",
                "",
                lead_data.get('etat', '')
            ]
            
            cell_range = f"{sheet_name}!A{row_num}:K{row_num}"
            body = {"values": [updated_row]}
            
            self.service.spreadsheets().values().update(
                spreadsheetId=self.sheet_id,
                range=cell_range,
                valueInputOption="USER_ENTERED",
                body=body
            ).execute()
            
            logger.info(f"✏️ Lead {phone} mis à jour ligne {row_num}")
            return True
            
        except Exception as e:
            logger.error(f"Erreur mise à jour lead: {e}")
            return False
    
    def delete_lead(self, sheet_name: str, phone: str) -> bool:
        """Supprime un lead (vide la ligne)"""
        try:
            # Trouver la ligne avec ce téléphone
            range_name = f"{sheet_name}!A:K"
            result = self.service.spreadsheets().values().get(
                spreadsheetId=self.sheet_id,
                range=range_name
            ).execute()
            
            values = result.get('values', [])
            row_num = None
            
            for i, row in enumerate(values[1:], start=2):
                if len(row) > 3 and self._clean_phone(row[3]) == phone:
                    row_num = i
                    break
            
            if not row_num:
                logger.warning(f"Lead {phone} non trouvé")
                return False
            
            # Vider la ligne
            empty_row = [""] * 11
            cell_range = f"{sheet_name}!A{row_num}:K{row_num}"
            body = {"values": [empty_row]}
            
            self.service.spreadsheets().values().update(
                spreadsheetId=self.sheet_id,
                range=cell_range,
                valueInputOption="USER_ENTERED",
                body=body
            ).execute()
            
            logger.info(f"🗑️ Lead {phone} supprimé ligne {row_num}")
            return True
            
        except Exception as e:
            logger.error(f"Erreur suppression lead: {e}")
            return False

    def _clean_phone(self, phone: str) -> str:
        if not phone:
            return ""
        phone = str(phone).strip().replace(" ", "").replace("-", "").replace(".", "")
        if phone.startswith("0") and len(phone) == 10:
            return phone
        return phone
