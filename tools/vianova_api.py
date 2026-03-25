#!/usr/bin/env python3
"""
Module API Miizy (Vianova) - Récupération stock immobilier
"""
import re
import requests
import json
import random
import logging
from pathlib import Path
from typing import List, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

CONFIG = json.load(open(Path(__file__).parent.parent / "config.json"))
BASE_URL = CONFIG["vianova"]["api_base_url"].rstrip('/')
API_KEY = CONFIG["vianova"]["api_key"]

# Mapping typologie utilisateur → nombre de pièces (rooms)
# Seules les properties avec status == 0 sont disponibles
# 0=AVAILABLE, 1=optionné, 2=vendu, 4=archivé
TYPO_TO_ROOMS = {
    "T1": 1, "F1": 1, "studio": 1, "1 pièce": 1, "une pièce": 1,
    "T2": 2, "F2": 2, "2 pièces": 2, "deux pièces": 2,
    "T3": 3, "F3": 3, "3 pièces": 3, "trois pièces": 3,
    "T4": 4, "F4": 4, "4 pièces": 4, "quatre pièces": 4,
    "T5": 5, "F5": 5, "5 pièces": 5, "cinq pièces": 5,
}


def _typo_to_rooms(typo: str) -> Optional[int]:
    """Convertit une typologie texte en nombre de pièces (int) ou None."""
    if not typo:
        return None
    t = typo.strip()
    # Correspondance directe (insensible à la casse)
    for k, v in TYPO_TO_ROOMS.items():
        if t.upper() == k.upper():
            return v
    # Fallback : extraire le premier chiffre
    m = re.search(r'\d+', t)
    return int(m.group()) if m else None


class VianovaAPI:
    """Client API Miizy / Vianova"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        })

    def get_cities(self) -> List[Dict]:
        """Récupère la liste des villes disponibles"""
        try:
            response = self.session.get(f"{BASE_URL}/cities", timeout=30)
            response.raise_for_status()
            data = response.json()
            return data if isinstance(data, list) else data.get("data", [])
        except Exception:
            return []

    def find_city_slugs(self, city_name: str) -> list:
        """
        Retourne TOUS les slugs correspondant à une ville.
        Gère les cas multi-arrondissements (Paris → [paris-1, paris-4, ..., paris-20]).
        """
        if not city_name:
            return []

        city_lower = city_name.lower().strip()
        city_norm  = city_lower.replace(" ", "-").replace("'", "-")
        cities = self.get_cities()
        matched = []

        for city in cities:
            name = city.get("name", "").lower()
            slug = city.get("slug", "").lower()
            # Correspondance exacte
            if city_lower in (name, slug) or city_norm == slug:
                return [city.get("slug")]
            # Correspondance préfixe (ex: "paris" → "paris-13", "paris-14"…)
            if (slug.startswith(city_norm + "-")
                    or name.startswith(city_lower + " ")
                    or name.startswith(city_lower + ",")):
                matched.append(city.get("slug"))

        if matched:
            return matched
        # Fallback: slug brut
        return [city_norm]

    def find_city_slug(self, city_name: str) -> str:
        """Retourne le premier slug trouvé (rétrocompat)."""
        slugs = self.find_city_slugs(city_name)
        return slugs[0] if slugs else city_name.lower().replace(" ", "-")

    def get_stock_by_city(self, city_slug: str, typologie: str = None) -> Dict:
        """
        Récupère et filtre le stock pour une ville.
        - Supporte plusieurs slugs séparés par | (ex: paris-13|paris-14)
        - Compte UNIQUEMENT les properties avec status == 0 (AVAILABLE)
        - Si `typologie` fournie : filtre sur rooms == n correspondant
        """
        slugs = city_slug.split("|") if "|" in city_slug else [city_slug]
        target_rooms = _typo_to_rooms(typologie) if typologie else None

        all_programs = []
        for slug in slugs:
            url = f"{BASE_URL}/stock/cities/{slug}"
            logger.info(f"[Miizy] GET {url} (typo={typologie}, rooms={target_rooms})")
            try:
                response = self.session.get(url, timeout=30)
                logger.info(f"[Miizy] status={response.status_code} len={len(response.text)}")
                if response.status_code >= 400:
                    continue
                data = response.json()
                programs = data.get("stock", []) if isinstance(data, dict) else []
                all_programs.extend(programs)
            except Exception as e:
                logger.error(f"[Miizy] erreur slug={slug}: {e}")
                continue

        # Compter les lots : status == 0 UNIQUEMENT
        by_rooms: Dict[str, int] = {}
        for program in all_programs:
            for prop in program.get("properties", []):
                # Ignorer tout ce qui n'est pas strictement disponible
                if prop.get("status") != 0:
                    continue
                rooms = prop.get("rooms")
                if rooms is None:
                    continue
                label = f"T{rooms}"
                by_rooms[label] = by_rooms.get(label, 0) + 1

        logger.info(f"[Miizy] ville={city_slug} by_rooms={by_rooms} target_rooms={target_rooms}")

        if target_rooms is not None:
            t_key = f"T{target_rooms}"
            count = by_rooms.get(t_key, 0)
            return {
                "city": city_slug,
                "total_lots": count,
                "by_typology": {t_key: count} if count > 0 else {},
                "error": None,
            }

        total = sum(by_rooms.values())
        return {
            "city": city_slug,
            "total_lots": total,
            "by_typology": by_rooms,
            "error": None,
        }

    def format_stock_message(self, city: str, stock_data: Dict,
                              requested_typo: str = None) -> str:
        """Formate un message d'annonce de stock de façon naturelle."""
        total = stock_data.get("total_lots", 0)
        by_typo = stock_data.get("by_typology", {})

        # Normaliser le label affiché : "2 pièces" → "T2", "F3" → "T3"
        def _display_label(typo: str) -> str:
            rooms = _typo_to_rooms(typo)
            return f"T{rooms}" if rooms else typo.strip().upper()

        if total == 0:
            if requested_typo:
                t = _display_label(requested_typo)
                return (f"À {city}, nous n'avons pas de {t} disponible actuellement. "
                        f"Souhaitez-vous élargir à une autre ville ou un autre type de bien ?")
            return (f"À {city}, nous n'avons malheureusement pas de disponibilités "
                    f"correspondant à votre recherche pour le moment.")

        intros = [f"À {city},", f"Côté {city},", f"Sur {city},"]
        intro = random.choice(intros)

        if requested_typo:
            # Label normalisé = jamais un autre type que celui demandé
            t = _display_label(requested_typo)
            count = total  # by_typology contient déjà uniquement ce type
            if count == 1:
                return f"{intro} nous avons 1 {t} disponible actuellement."
            return f"{intro} nous avons {count} {t} disponibles actuellement."

        if total == 1:
            return f"{intro} nous avons 1 bien disponible actuellement."

        typo_summary = []
        for t, c in sorted(by_typo.items(), key=lambda x: -x[1])[:3]:
            typo_summary.append(f"{c} {t}" if c > 1 else f"1 {t}")

        return f"{intro} nous avons {total} biens disponibles ({', '.join(typo_summary)})."


# Instance globale
api = VianovaAPI()


def get_stock(city: str, typologie: str = None) -> Tuple[Dict, str]:
    """Récupère le stock (agrège les arrondissements si nécessaire)."""
    if not city:
        return (
            {"total_lots": 0, "by_typology": {}, "error": "no_city"},
            "Je n'ai pas vos critères de recherche précis. "
            "Pouvez-vous me préciser la ville et le type de bien ?",
        )
    slugs = api.find_city_slugs(city)
    combined_slug = "|".join(slugs) if slugs else city.lower().replace(" ", "-")
    stock = api.get_stock_by_city(combined_slug, typologie)
    message = api.format_stock_message(city, stock, typologie)
    return stock, message


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)

    tests = [
        ("Saint-Genis-Pouilly", "T3"),
        ("Saint-Genis-Pouilly", None),
        ("Paris", "T2"),
        ("Bordeaux", "T4"),
        ("Nantes", "2 pièces"),
    ]

    for city, typo in tests:
        print(f"\n--- {city} / {typo or 'tous'} ---")
        stock, msg = get_stock(city, typo)
        print(f"  total={stock['total_lots']}  by_typology={stock['by_typology']}")
        print(f"  → {msg}")
