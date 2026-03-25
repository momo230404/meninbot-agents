# Tests de l'API Vianova

## ✅ Endpoints testés

### 1. POST /api/campaign/launch
**Status**: ✅ WORKING
**Test**: Lancement de campagne en dry-run
```bash
curl -X POST http://localhost:5000/api/campaign/launch \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Bonjour {prenom}",
    "batch_size": 2,
    "dry_run": true,
    "leads": [
      {"prenom": "Jean", "nom": "Dupont", "telephone": "+33612345678", "ville": "Paris"}
    ]
  }'
```
**Response**: `{"batch_size":2,"message":"Campagne lancée en dry-run","success":true}`

### 2. GET /api/stats
**Status**: ✅ WORKING
```bash
curl http://localhost:5000/api/stats
```
**Response**: `{"stats":{"closed":0,"rdv_confirmed":0,"rdv_proposed":0,"sent":0,"total_leads":0,"waiting":0},"success":true}`

### 3. GET /api/templates/{key}/preview
**Status**: ✅ WORKING
**Available templates**: `initial`, `relance_24h`, `relance_72h`
```bash
curl http://localhost:5000/api/templates/initial/preview
```

### 4. GET /api/conversations
**Status**: ❌ NOT IMPLEMENTED (returns 404)
**Handled in frontend**: Gracefully falls back to empty list

---

## 📋 Dashboard Refactoring Checklist

### 1. FUSIONNER les onglets "Lancement Campagne" et "Leads" ✅
- ✅ Colonne gauche: liste des leads avec recherche/filtre
- ✅ Colonne droite: formulaire de campagne + aperçu message
- ✅ Bouton "Lancer" toujours visible (sticky button en bas)
- ✅ Sélection lead = aperçu message avec variables résolues

### 2. NOUVEL ONGLET "Conversation" ✅
- ✅ Style WhatsApp: deux colonnes
- ✅ Gauche: liste conversations (phone + dernier message + timestamp)
- ✅ Droite: détail conversation avec messages en bulles
- ✅ Envoi messages manuels
- ✅ Graceful fallback si endpoint non disponible

### 3. FIXER LE LANCEMENT DE CAMPAGNE ✅
- ✅ Vérifier message non-vide (validation frontend)
- ✅ Afficher erreurs correctement (alert messages)
- ✅ Loading spinner pendant envoi (bouton disabled + spinner)
- ✅ Gestion des leads vides (validation)

### 4. GARDER les autres onglets ✅
- ✅ 📊 Statistiques
- ✅ 📝 Templates (NOUVEAU - permet d'éditer les templates)
- ✅ 🔔 Relances (NOUVEAU - affiche les relances auto)

---

## 🎯 Améliorations apportées

1. **Layout two-column pour Campaign+Leads**
   - Donne plus de surface d'édition pour le message
   - Leads toujours visibles pour sélection rapide
   - Aperçu du lead en bas du formulaire

2. **Loading spinner**
   - Désactive le bouton pendant l'envoi
   - Affiche un spinner avec texte
   - Restore l'état après complétion

3. **Alert system**
   - Messages de succès/erreur avec auto-dismiss (4s)
   - Design cohérent avec le reste

4. **Responsive**
   - Sur mobile: layout passe à single column
   - Grids adaptatifs

---

## 🧪 Cas de test
- Message vide → Rejection ❌
- Lead ajouté → Selection ✅
- Aperçu message → Remplacement variables ✅
- Lancement → Loading + Spinner ✅
- Stats → Chargement asynchrone ✅
