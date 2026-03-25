#!/usr/bin/env python3
"""Module API Miizy - Stock immobilier avec gestion anti-bug"""
import requests
import json
import re
from typing import List, Dict, Optional, Any
import logging

logger = logging.getLogger("miizy_api")

class MiizyAPI:
    """Client API Miizy avec validation stricte des réponses"""
    
    def __init__(self, api_key: str, base_url: str = "https://miizy.com/miizy"):
        self.api_key = api_key
        self.base_url = base_url
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json"
        }
    
    def search_stock(
        self,
        ville: Optional[str] = None,
        typologie: Optional[str] = None,
        budget_max: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Recherche le stock immobilier avec validation stricte."""
        try:
            params = {}
            if ville:
                ville_clean = self._clean_ville(ville)
                if ville_clean:
                    params["ville"] = ville_clean
                    
            if typologie:
                typo_clean = self._clean_typologie(typologie)
                if typo_clean:
                    params["typologie"] = typo_clean
            
            logger.info(f"Recherche stock: ville={ville}, typo={typologie}")
            
            response = requests.get(
                f"{self.base_url}/stock",
                headers=self.headers,
                params=params,
                timeout=15
            )
            response.raise_for_status()
            
            data = response.json()
            biens = self._parse_stock_response(data, budget_max)
            
            logger.info(f"Stock trouvé: {len(biens)} biens")
            return biens
            
        except Exception as e:
            logger.error(f"Erreur API Miizy: {e}")
            return []
    
    def format_stock_summary(self, biens: List[Dict[str, Any]], ville: str, typologie: str) -> str:
        """Formate un résumé du stock disponible"""
        if not biens:
            return (
                f"Je comprends que vous recherchez un {typologie} à {ville}. "
                f"Malheureusement, je n'ai pas de biens correspondant actuellement. "
                f"Puis-je vous notifier dès qu'une nouveauté arrive ?"
            )
        
        prix_list = [b["prix"] for b in biens if b.get("prix")]
        prix_min = min(prix_list) if prix_list else None
        prix_max = max(prix_list) if prix_list else None
        
        if len(biens) == 1:
            prix_str = f"{biens[0]['prix']:,.0f}€".replace(",", " ") if biens[0].get("prix") else "prix sur demande"
            return (
                f"J'ai un {biens[0]['typologie']} à {biens[0]['ville']} "
                f"pour {prix_str}. Souhaitez-vous plus d'informations ?"
            )
        
        if prix_min and prix_max:
            prix_str = f"entre {prix_min:,.0f}€ et {prix_max:,.0f}€".replace(",", " ")
        elif prix_min:
            prix_str = f"à partir de {prix_min:,.0f}€".replace(",", " ")
        else:
            prix_str = "prix sur demande"
        
        return (
            f"J'ai {len(biens)} {typologie}(s) disponible(s) à {ville} "
            f"{prix_str}. Je peux vous envoyer les détails ?"
        )
    
    def _clean_ville(self, ville: str) -> str:
        return ville.strip() if ville else ""
    
    def _clean_typologie(self, typologie: str) -> str:
        match = re.search(r'[Tt](\d+)', str(typologie))
        if match:
            return f"T{match.group(1)}"
        match = re.search(r'^(\d)$', str(typologie))
        if match:
            return f"T{match.group(1)}"
        return typologie
    
    def _parse_stock_response(self, data: Dict, budget_max: Optional[int] = None) -> List[Dict[str, Any]]:
        original = data.get("original", {})
        biens_bruts = original.get("data", [])
        
        biens_filtres = []
        for bien in biens_bruts:
            if not isinstance(bien, dict):
                continue
            bien_clean = {
                "id": bien.get("id"),
                "titre": bien.get("title", "Bien"),
                "ville": bien.get("city", ""),
                "typologie": bien.get("typology", ""),
                "prix": self._extract_prix(bien.get("price")),
                "surface": bien.get("surface"),
                "url": bien.get("url", "")
            }
            if budget_max and bien_clean["prix"] and bien_clean["prix"] > budget_max:
                continue
            biens_filtres.append(bien_clean)
        return biens_filtres
    
    def _extract_prix(self, prix_raw) -> Optional[int]:
        try:
            if isinstance(prix_raw, (int, float)):
                return int(prix_raw)
            if isinstance(prix_raw, str):
                prix_str = re.sub(r'[^\d]', '', prix_raw)
                if prix_str:
                    return int(prix_str)
            return None
        except:
            return None