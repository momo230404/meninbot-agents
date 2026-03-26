---
name: OpenClow Project Context
description: Stack, contraintes et mission du projet OpenClow sur VPS Hostinger
type: project
---

Projet OpenClow déployé sur VPS Hostinger (Docker).

**Stack :**
- LLM : Kimi 2.5 (moonshot-v1) — GRATUIT, non négociable (pas d'Anthropic/OpenAI payant)
- Messagerie : Evolution API (WhatsApp)
- Mémoire/session : Redis
- Code : Python
- Données : Google Sheets (leads, stocks, statuts de relance)

**Problème :** Kimi 2.5 a des limites (contexte, raisonnement, suivi d'instructions complexes). L'utilisateur ne veut pas changer de LLM — il veut contourner intelligemment.

**Mission :**
1. Prompt engineering adapté à Kimi (court, clair, structuré)
2. Déléguer la logique complexe au code Python
3. Utiliser Redis pour compenser les limites mémoire/contexte
4. Google Sheets = source de vérité, éviter de surcharger le LLM

**Règle absolue :** Aucune API payante. Optimiser avec ce qu'on a.

**Why:** L'utilisateur a une contrainte budget stricte et a déjà tout déployé.
**How to apply:** Toujours proposer des solutions avec les outils existants, jamais suggérer de changer de LLM ou d'ajouter des services payants.
