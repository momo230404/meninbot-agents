---
name: Agent Vianova WhatsApp Relance — Dashboard Multi-Agent
description: Tout sur le dashboard vianova.meninbot.com avec 2 agents WhatsApp (Vianova=Daniel, Miizy=Alex) — infra, fichiers, architecture, bugs résolus, auth, comptes
type: project
---

# Dashboard Multi-Agent WhatsApp — vianova.meninbot.com

## Les 2 agents — noms à retenir

| Identifiant | Nom commercial | Nom de l'agent IA | Cible |
|---|---|---|---|
| `vianova` | **Agent Vianova WhatsApp** | **Daniel** | Particuliers cherchant immobilier neuf |
| `miizy` | **Agent Miizy WhatsApp** | **Alex** | Professionnels de l'immobilier |

Quand l'utilisateur dit :
- "agent Vianova", "Daniel", "Vianova" → agent `vianova`
- "agent Miizy", "Alex", "Miizy" → agent `miizy`
- "les 2 agents", "le dashboard" → `vianova.meninbot.com`

---

## Infrastructure

| Élément | Valeur |
|---|---|
| VPS | Hostinger — IP `187.124.33.83` |
| Accès SSH | `ssh root@187.124.33.83` (clé ed25519 locale acceptée) |
| Conteneur Docker | `openclaw-td9j-openclaw-1` |
| Workspace (hôte) | `/docker/openclaw-td9j/data/.openclaw/workspace/vianova-agent/` |
| Workspace (conteneur) | `/data/.openclaw/workspace/vianova-agent/` |
| Dashboard URL | `https://vianova.meninbot.com` et `https://miizy.meninbot.com` |
| Dashboard API | Flask port 5000, routé par Traefik HTTPS |
| Academy | `https://academy.meninbot.com` → Python `http.server` port 5001, dossier `/docker/academy/` |
| GitHub repo | `https://github.com/momo230404/meninbot-agents` |
| Evolution API (Vianova) | instance "Daniel de Vianova" |
| Evolution API (Miizy Adam) | instance "Adam", clé `914EA13DA82D-4A14-AE5F-737A67EFAC9F`, phone +33756880173 |
| Evolution API (Miizy Mohamed) | instance "Mohamed de Miizy", clé `ADF1DE707369-4B10-88BA-DDF09F637016`, phone +33756865554 |
| Evolution API (Miizy Dorian) | instance "Dorian de Miizy", clé `3F9966F3459B-4F0B-8998-BC8CF44C4E47`, phone +33756863811 |

**Déploiement (méthode actuelle — via git pull) :**
```bash
# 1. Modifier les fichiers dans /tmp/
# 2. Copier dans le clone local
cp /tmp/fichier.py /tmp/meninbot-agents/fichier.py
# 3. Commit + push GitHub
cd /tmp/meninbot-agents && git add fichier.py && git commit -m "..." && git push origin master
# 4. Pull sur VPS + restart
ssh root@187.124.33.83 "git config --global --add safe.directory /docker/openclaw-td9j/data/.openclaw/workspace/vianova-agent; cd /docker/openclaw-td9j/data/.openclaw/workspace/vianova-agent && git pull && docker restart openclaw-td9j-openclaw-1"
```

---

## Fichiers clés

```
vianova-agent/
├── agent_ia_minimal.py       # Agent Vianova (Daniel) — logique conversationnelle
├── miizy_agent.py            # Agent Miizy (Alex)
├── dashboard_api.py          # Flask API + webhooks + _AgentProxy multi-agent + auth
├── dashboard.html            # UI dashboard
├── leads_manager.py          # Gestion leads Redis+JSON (fallback JSON si Redis KO)
├── redis_client.py           # Client Redis (Upstash TLS — parfois instable)
├── conversation_memory.py    # Mémoire JSON par numéro (conversations/)
├── config.json               # Config API keys, instances Evolution, Miizy, Google
├── users.json                # Comptes utilisateurs (email, hash mdp, role, agent)
├── google_credentials.json   # OAuth2 client Google (Calendar)
├── token.json                # Token OAuth2 Google Calendar connecté
├── leads.json                # Leads Vianova (backup JSON)
├── miizy_leads.json          # Leads Miizy (backup JSON)
├── templates_custom.json     # Templates personnalisés Vianova
├── miizy_templates.json      # Templates personnalisés Miizy
├── hidden_conversations.json # Numéros masqués dans conversations
├── conversations/            # Mémoire JSON par prospect (Vianova)
├── tools/
│   ├── vianova_api.py        # Client API Miizy (stock immo)
│   └── calendar_api.py       # Google Calendar (OAuth2 via token.json)
└── logs/dashboard_api.log
```

---

## Authentification (ajoutée cette session)

### Page de connexion : `https://vianova.meninbot.com/login`
- Protège `/` et `/dashboard` — redirige vers `/login` si pas connecté
- Sessions Flask (`app.secret_key`)
- Comptes stockés dans `users.json` (werkzeug password_hash)

### Comptes existants

| Nom | Email | Mot de passe | Role | Accès |
|---|---|---|---|---|
| **Admin** | `admin@vianova.meninbot.com` | `AdminVianova2026!` | admin | Complet |
| **Daniel De Jesus** | `ddejesus@vianova-groupe.fr` | `Danielvianova123@` | daniel | Vianova uniquement |

### Lien Daniel (interface verrouillée) : `https://vianova.meninbot.com/?agent=vianova`
- Dropdown agent masqué → badge fixe "⚡ Agent Vianova WhatsApp — Daniel"
- Onglets masqués : Campagnes, Templates, Agent (`nav-admin-only`)
- Onglets visibles : Leads, Conversations, Agenda, Statistiques

### Routes auth
- `GET /login` / `POST /login` → page connexion
- `GET /logout` → déconnexion
- `GET /api/auth/me` → infos utilisateur connecté (401 si non connecté)

### Routes admin (role=admin uniquement)
- `GET /api/admin/users` → liste comptes
- `POST /api/admin/users` → créer compte
- `DELETE /api/admin/users/<email>` → supprimer compte
- `PUT /api/admin/users/<email>` → modifier compte

---

## Architecture multi-agent (dashboard_api.py)

### _AgentProxy
Proxy transparent qui route vers Vianova ou Miizy selon `request.path` :
```python
leads_manager = _AgentProxy(_vianova_leads_manager, miizy_leads_manager)
evolution_api = _AgentProxy(_vianova_evolution_api, miizy_evolution_api)
# Si '/miizy/' dans request.path → miizy_*
# Sinon → vianova_*
```

### Routes auto-mirrées
Toutes les routes `/api/*` sont automatiquement disponibles sur `/miizy/api/*`.

### Webhooks
- Vianova : `POST /webhook/whatsapp` → `_process_buffered(phone)`
- Miizy : `POST /miizy/webhook/whatsapp` → `_process_miizy_buffered(phone)`

### Redis (Upstash TLS — limite 500k req/mois atteinte)
- Vianova conv : `conv:{phone}`, leads : `lead:{phone}`
- Miizy session : **migré vers fichiers JSON locaux** dans `miizy_sessions/{phone}.json` (TTL 7 jours)
- Déduplication messages Miizy : dict en mémoire `_MSG_DEDUP` (remplace Redis `miizy:msgid:*`)
- **IMPORTANT** : Redis parfois KO → `get_lead()` et `send_message()` ont un fallback JSON local

---

## Google Calendar (Daniel)

- **Compte connecté** : `ddejesus@vianova-groupe.fr`
- **OAuth2** : token dans `token.json`, credentials dans `google_credentials.json`
- **Client ID** : `314257602733-ajfavp08k741rgecnli9ovhjetr3udvj.apps.googleusercontent.com`
- **Reconnexion** : `https://vianova.meninbot.com/oauth/start`
- **Bandeau agenda** : affiche l'email connecté dans l'onglet Agenda

---

## Agent Vianova (Daniel)

- **Cible** : particuliers cherchant immobilier neuf
- **Champs leads** : Nom, Prénom, Téléphone, Ville, Typologie, Budget
- **Stages** : `initial → waiting_info → rdv_propose → attente_creneau → rdv_confirme → clos`
- **RDV** : Google Calendar (`ddejesus@vianova-groupe.fr`), sans email obligatoire
- **Webhook Evolution** : instance "Daniel de Vianova"

---

## Agent Miizy (Alex)

- **Cible** : professionnels de l'immobilier (agents, promoteurs)
- **Champs leads** : Nom, Prénom, Téléphone uniquement (pas ville/typo/budget)
- **Stages** : `INIT → ATTENTE_TYPE_ACTIVITE → PITCH_ENVOYE → ATTENTE_CONFIRMATION_CALENDLY → RELANCE_APRES_NON → FERME`
- **Pas de RDV** : lien Calendly (`config.json["miizy"]["calendly_link"]`)
- **Webhook** : `POST /miizy/webhook/whatsapp`
- **3 commerciaux** : Adam (IA), Mohamed, Dorian — chacun a sa propre instance Evolution API
- **Sessions** : fichiers JSON dans `miizy_sessions/` (plus Redis)
- **LLM** : OpenAI gpt-4o-mini (config dans `config.json["llm"]`), switchable vers Anthropic via onglet "🔌 Connexion LLM" du dashboard

---

## Bugs résolus (sessions précédentes + cette session)

| Bug | Fix |
|---|---|
| Supprimer lead ne marchait pas | Suppression `confirm()` bloqué, remplacé par toast + fetch direct |
| `showAlert` plantait si conteneur caché | Null-check + fallback `showToast()` |
| Leads à contacter vides après ajout | `classifyLead` : `initial`/`message_a_envoyer` → toujours `contacter` |
| Phone avec `+` → "Lead non trouvé" | `delete_lead` essaie phone avec et sans `+` |
| Agent ne répondait pas (NameError `re`) | `import re` manquant dans `dashboard_api.py` |
| Variables `{Prenom}` etc. non remplacées dans campagne | Redis KO → `get_lead()` retournait None → fallback JSON ajouté dans `get_lead()` et `send_message()` |
| Messages prospect invisibles dans conversations | Evolution API ne stocke que les sortants → fusion avec `ConversationMemory` JSON local |
| Template campagne ne chargeait pas le texte sauvegardé | `loadTemplate()` appelait `/preview` (hardcodé) → corrigé vers `GET /api/templates` |
| `deleteConversation` supprimait aussi le lead | Revert : `delete_conversation` ne supprime plus que la mémoire conversation |

---

## Règles métier

- Templates sauvegardés : `templates_custom.json` (Vianova) et `miizy_templates.json` (Miizy)
- Leads auto-mirrés vers `/miizy/api/*` : zéro modification pour nouveaux endpoints
- Redis instable (Upstash) : toujours prévoir fallback JSON pour les opérations critiques

**Why:** L'utilisateur gère 2 campagnes WhatsApp distinctes depuis un seul dashboard. Chaque agent cible une audience différente.
**How to apply:** Toujours demander "Vianova ou Miizy ?" si la requête est ambiguë. Ne jamais mélanger les données des 2 agents.
