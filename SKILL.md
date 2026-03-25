# Vianova Agent - WhatsApp Relance Automatique

## Description
Agent de relance WhatsApp pour l'immobilier neuf (Vianova/Viandro Groupe).
Remplace N8N par une solution OpenClaw native, plus robuste et naturelle.

## Architecture
- **Campagne**: Envoie initial depuis Google Sheets → WhatsApp
- **Inbound**: Réception webhooks Evolution API → Réponse IA

## Fichiers
- `campain.py` - Lance les campagnes de relance
- `inbound.py` - Webhook server pour réponses
- `conversation_memory.py` - Gestion mémoire par conversation
- `tools/vianova_api.py` - Connexion API stock immo
- `tools/calendar.py` - Création RDV Google Calendar
- `tools/evolution.py` - Envoi WhatsApp via Evolution API

## Configuration requise
Voir `config.json` - À remplir avec les credentials
