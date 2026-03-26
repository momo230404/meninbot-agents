---
name: Toujours push GitHub après modif Miizy
description: Après chaque modification de l'agent Miizy (fichiers sur VPS), toujours commit + push vers GitHub
type: feedback
---

Après chaque modification sur le VPS pour l'agent Miizy, toujours finir par un git commit + push vers le dépôt GitHub.

**Why:** L'utilisateur veut que le code GitHub soit toujours synchronisé avec la production VPS. Le remote est déjà configuré dans le workspace.

**How to apply:** À la fin de chaque session de modification Miizy (miizy_agent.py, dashboard_api.py, etc.), exécuter :
```bash
ssh root@187.124.33.83 "docker exec openclaw-td9j-openclaw-1 bash -c 'cd /data/.openclaw/workspace/vianova-agent && git add <fichiers modifiés> && git commit -m \"<message>\" && git push origin master'"
```
Repo : https://github.com/momo230404/meninbot-agents (remote déjà configuré avec token dans l'URL).
