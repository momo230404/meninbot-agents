# 📊 Dashboard Gestion des Leads - VIANOVA

## Vue d'ensemble

Dashboard moderne et complet pour gérer les leads immobiliers avec campagnes de messages, suivi d'état, et import/export CSV.

## ✨ Fonctionnalités

### 1. 👥 Gestion des Leads (Leads)
- **Table complète avec 10 colonnes** :
  - Nom, Prénom, Téléphone, Ville
  - Typologie (T1-T5+), Budget
  - Date de dernier contact, Date d'envoi
  - État (9 statuts), Actions
- **Tri par colonne** : Cliquez sur l'en-tête pour trier ↑↓
- **Recherche globale** : 🔍 barre de recherche
- **Filtres avancés** : Nom, Prénom, Ville, Téléphone, État
- **Ajout manuel** : Bouton "➕ Ajouter un lead" → formulaire modal
- **Import CSV** : Bouton "📥 Importer CSV" avec parsing automatique
- **Template CSV** : Télécharger un exemple pour structurer vos données
- **Actions sur chaque lead** :
  - ✏️ **Éditer** : Modification modale complète
  - 🗑️ **Supprimer** : Suppression avec confirmation
  - 📞 **Mettre à jour dernier contact** : Enregistre la date du jour

### 2. 🚀 Campagnes
- **Éditeur de message** : Avec aperçu en temps réel
- **Variables disponibles** : {prenom}, {nom}, {ville}, {budget}
- **Templates rapides** : Charger Initial, Relance 24h, Relance 72h
- **Paramètres** :
  - Nombre de leads à traiter
  - Mode test (sans envoi)
- **Lancement de campagne** : Bouton "▶️ LANCER LA CAMPAGNE"

### 3. 📝 Templates
- Gestion des 3 templates principaux
- Sauvegarde individuelle de chaque template
- Utilisation dans les campagnes

### 4. 📊 Statistiques
- Total de campagnes
- Messages envoyés
- RDV total
- Affaires clos

### 5. 💬 Conversations
- Section prête pour conversations futures

---

## 📋 Structures de Données

### Lead Object
```json
{
  "id": 1,
  "nom": "Dupont",
  "prenom": "Jean",
  "telephone": "+33612345678",
  "ville": "Paris",
  "typologie": "T2",
  "budget": "250000€",
  "date_dernier_contact": "2024-03-15",
  "date_envoi": "2024-03-10",
  "etat": "en_cours"
}
```

**États possibles** :
- `initial` → Initial
- `message_a_envoyer` → Message à envoyer
- `en_cours` → En cours
- `rdv_propose` → RDV proposé
- `rdv_confirme` → RDV confirmé
- `relance` → Relance
- `clos` → Clos

### Typologies
T1, T2, T3, T4, T5+

---

## 🔌 Endpoints API Attendus

### Leads Management

#### GET /api/leads
Lister tous les leads
```bash
curl http://localhost:5000/api/leads
```
**Response** :
```json
{
  "success": true,
  "leads": [
    {
      "id": 1,
      "nom": "Dupont",
      "prenom": "Jean",
      ...
    }
  ]
}
```

#### POST /api/leads
Ajouter un lead
```bash
curl -X POST http://localhost:5000/api/leads \
  -H "Content-Type: application/json" \
  -d '{
    "nom": "Dupont",
    "prenom": "Jean",
    "telephone": "+33612345678",
    "ville": "Paris",
    "etat": "initial"
  }'
```

#### POST /api/leads/import
Importer plusieurs leads (CSV)
```bash
curl -X POST http://localhost:5000/api/leads/import \
  -H "Content-Type: application/json" \
  -d '{
    "leads": [
      { "nom": "...", "prenom": "...", ... },
      { "nom": "...", "prenom": "...", ... }
    ]
  }'
```

#### PUT /api/leads/{id}
Éditer un lead
```bash
curl -X PUT http://localhost:5000/api/leads/1 \
  -H "Content-Type: application/json" \
  -d '{
    "etat": "rdv_propose",
    "date_dernier_contact": "2024-03-15"
  }'
```

#### DELETE /api/leads/{id}
Supprimer un lead
```bash
curl -X DELETE http://localhost:5000/api/leads/1
```

### Campagnes

#### POST /api/campaign/launch
Lancer une campagne
```bash
curl -X POST http://localhost:5000/api/campaign/launch \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Bonjour {prenom}, ...",
    "batch_size": 10,
    "dry_run": false,
    "leads": [ ... ]
  }'
```

### Templates

#### POST /api/templates/{templateKey}
Sauvegarder un template
```bash
curl -X POST http://localhost:5000/api/templates/initial \
  -H "Content-Type: application/json" \
  -d '{ "content": "Bonjour..." }'
```

#### GET /api/templates/{templateKey}/preview
Charger un template
```bash
curl http://localhost:5000/api/templates/initial/preview
```

### Statistiques

#### GET /api/stats
Récupérer les statistiques
```bash
curl http://localhost:5000/api/stats
```
**Response** :
```json
{
  "success": true,
  "stats": {
    "total_campaigns": 5,
    "messages_sent": 150,
    "rdv_total": 25,
    "closed_total": 8
  }
}
```

---

## 📥 Format CSV pour Import

### Headers acceptés :
```
nom,prenom,telephone,ville,typologie,budget,date_dernier_contact,date_envoi,etat
```

### Exemple complet :
```csv
nom,prenom,telephone,ville,typologie,budget,date_dernier_contact,date_envoi,etat
Dupont,Jean,+33612345678,Paris,T2,250000€,2024-01-15,2024-03-10,initial
Martin,Marie,+33623456789,Lyon,T3,350000€,2024-02-20,2024-03-12,en_cours
Bernard,Pierre,+33634567890,Marseille,T1,150000€,,2024-03-14,message_a_envoyer
```

**Notes** :
- Les colonnes peuvent être dans n'importe quel ordre
- Minimum requis : `nom`, `prenom`, `telephone`
- Les colonnes supplémentaires sont ignorées
- Les valeurs vides sont autorisées (sauf pour les 3 requises)

---

## 🎨 Styles et Thème

### Couleurs principales
- **Primaire** : Dégradé bleu (#0099ff → #0066ff)
- **Succès** : Dégradé teal (#00d4aa → #00aa88)
- **Danger** : Rouge (#ff4757)
- **Fond** : Gris clair (#f8fafc, #e2e8f0)

### Composants
- Boutons avec hover et effets
- Modals animés
- Badges d'état colorés
- Tables avec scroll horizontal
- Responsive design (mobile, tablet, desktop)

---

## 🚀 Utilisation

### 1. Ajouter des leads
**Option A** : Manuellement
1. Cliquez "➕ Ajouter un lead"
2. Remplissez le formulaire
3. Cliquez "💾 Enregistrer"

**Option B** : Importer CSV
1. Cliquez "📥 Importer CSV"
2. Sélectionnez un fichier .csv
3. Les leads sont ajoutés automatiquement

**Option C** : Télécharger template
1. Cliquez "📋 Template"
2. Ouvrez le fichier CSV dans Excel
3. Remplissez les lignes
4. Importez le fichier

### 2. Gérer les leads
- **Éditer** : Cliquez ✏️
- **Supprimer** : Cliquez 🗑️
- **Mettre à jour dernier contact** : Cliquez 📞
- **Trier** : Cliquez sur l'en-tête de colonne
- **Filtrer** : Utilisez la barre de recherche ou les filtres avancés

### 3. Lancer une campagne
1. Allez à "🚀 Campagnes"
2. Écrivez votre message (avec variables {prenom}, {nom}, etc.)
3. Sélectionnez un template ou écrivez libre
4. Définissez le nombre de leads
5. Cochez "Mode test" si vous voulez tester d'abord
6. Cliquez "▶️ LANCER LA CAMPAGNE"

### 4. Gérer les templates
1. Allez à "📝 Templates"
2. Remplissez le contenu de chaque template
3. Cliquez "💾 Enregistrer"
4. Les templates sont utilisables dans les campagnes

### 5. Voir les statistiques
1. Allez à "📊 Statistiques"
2. Visualisez les KPIs principaux

---

## 🔧 Installation/Configuration

### 1. Placer le fichier
```
/data/.openclaw/workspace/vianova-agent/dashboard.html
```

### 2. Configurer l'API
Par défaut, le dashboard utilise :
```javascript
const API_URL = 'http://localhost:5000/api';
```

Modifiez si votre serveur est ailleurs :
```javascript
const API_URL = 'https://api.example.com';
```

### 3. Ouvrir dans le navigateur
```
http://localhost:8000/dashboard.html
```
(ou selon votre serveur local)

---

## 🐛 Debugging

### Vérifier les appels API
Ouvrez les DevTools (F12) → Console
Les erreurs s'affichent avec contexte

### Tester les endpoints
```bash
# Test de connexion
curl http://localhost:5000/api/leads

# Ajouter un lead test
curl -X POST http://localhost:5000/api/leads \
  -H "Content-Type: application/json" \
  -d '{"nom":"Test","prenom":"User","telephone":"+33600000000"}'
```

### Logs côté frontend
Le dashboard log les erreurs dans la console du navigateur

---

## ✅ Checklist Intégration

- [ ] Endpoint GET /api/leads
- [ ] Endpoint POST /api/leads
- [ ] Endpoint PUT /api/leads/{id}
- [ ] Endpoint DELETE /api/leads/{id}
- [ ] Endpoint POST /api/leads/import
- [ ] Endpoint POST /api/campaign/launch
- [ ] Endpoint POST /api/templates/{key}
- [ ] Endpoint GET /api/templates/{key}/preview
- [ ] Endpoint GET /api/stats
- [ ] Base de données avec schéma leads
- [ ] CORS activé pour localhost:5000
- [ ] Tests des formulaires
- [ ] Tests de l'import CSV

---

## 📞 Support

Pour toute question sur :
- **Fonctionnalités** : Lisez cette doc et les commentaires du code
- **API** : Vérifiez les endpoints ci-dessus
- **Styling** : Les styles sont inline dans le `<style>` de la page
- **JavaScript** : Le code est commenté dans la section `<script>`

---

**Version** : 1.0  
**Dernière mise à jour** : Mars 2024  
**Auteur** : Vianova Lead Manager
