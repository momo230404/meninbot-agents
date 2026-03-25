# 🚀 Guide Utilisateur - Vianova Dashboard

## 🎯 Vue d'ensemble

Le dashboard Vianova est un outil complet pour gérer vos campagnes de prospection immobilière avec WhatsApp. Il offre une interface intuitive pour :

- 🚀 Lancer des campagnes de messages personnalisés
- 💬 Gérer les conversations avec vos prospects
- 📝 Créer et modifier vos templates de messages
- 🔔 Configurer des relances automatiques
- 📊 Suivre vos statistiques en temps réel

---

## 📖 Guide par Onglet

### 1️⃣ 🚀 **CAMPAGNES** (Onglet Principal)

L'onglet Campagnes combine la gestion des leads et le lancement de campagnes dans une seule interface.

#### **Colonne Gauche: Gestion des Leads**

1. **Ajouter des leads manuellement:**
   - Cliquez sur la section "➕ Ajouter lead"
   - Remplissez les champs obligatoires: **Prénom*, Nom*, Téléphone***
   - Optionnel: Ville
   - Cliquez sur **"Ajouter"**
   - Le lead apparaît dans la liste "👥 Leads"

2. **Chercher un lead:**
   - Utilisez la barre de recherche "Rechercher..."
   - La liste se filtre en temps réel

3. **Sélectionner un lead:**
   - Cliquez sur un lead dans la liste
   - Le lead est surligné (fond bleu)
   - Ses infos s'affichent en bas du formulaire

#### **Colonne Droite: Formulaire de Campagne**

1. **Éditer le message:**
   - Écrivez votre message dans la zone "📧 Message"
   - Variables disponibles: `{prenom}`, `{ville}`, `{budget}`
   - L'aperçu se met à jour automatiquement

2. **Utiliser un template:**
   - **Initial**: Premier message de prospection
   - **24h**: Relance après 24h
   - **72h**: Relance après 72h
   - Cliquez sur le bouton pour charger le template

3. **Voir l'aperçu:**
   - Section "👁️ Aperçu" montre le message final
   - Les variables sont remplacées avec les données du lead sélectionné
   - Utile pour vérifier avant l'envoi

4. **Configurer les paramètres:**
   - **Nombre de leads**: Combien de leads à traiter (défaut: 10)
   - **Mode test**: ✓ pour tester sans envoi réel

5. **Lancer la campagne:**
   - Cliquez sur **"▶️ LANCER CAMPAGNE"**
   - Un spinner s'affiche pendant l'envoi
   - Message de succès ou erreur après traitement

---

### 2️⃣ 💬 **CONVERSATIONS**

Gérez vos conversations WhatsApp avec vos prospects.

#### **Fonctionnalités:**

- **Liste des conversations** (gauche): 
  - Affiche tous vos prospects
  - Filtrez avec "Rechercher..."
  - Voir le dernier message et la date

- **Détail conversation** (droite):
  - Historique complet des messages
  - Bulles stylisées (vous = bleu, prospect = gris)
  - Horodatage de chaque message
  - Champ pour envoyer une réponse manuelle
  - Bouton "📤" pour envoyer

#### **Comment ça marche:**

1. Sélectionnez une conversation dans la liste
2. Lisez l'historique à droite
3. Écrivez votre message dans le champ bas
4. Cliquez "📤" pour envoyer

---

### 3️⃣ 📝 **TEMPLATES**

Créez et modifiez vos modèles de message réutilisables.

#### **Templates disponibles:**

1. **Template Initial** - Premier contact (présentation + offre)
2. **Template Relance 24h** - Rappel après 24 heures
3. **Template Relance 72h** - Rappel après 3 jours

#### **Comment utiliser:**

1. Cliquez sur l'onglet "📝 Templates"
2. Modifiez le contenu de chaque template
3. Utilisez les variables: `{prenom}`, `{ville}`, `{budget}`, `{date_dernier_echange}`
4. Cliquez **"Enregistrer"** pour sauvegarder
5. Les templates seront disponibles lors du lancement de campagne

---

### 4️⃣ 🔔 **RELANCES**

Configurez vos relances automatiques.

#### **Relances par défaut:**

| Délai | Template | Statut |
|-------|----------|--------|
| 24 heures | relance_24h | Actif ✅ |
| 72 heures | relance_72h | Actif ✅ |

#### **Fonctionnement:**

- Les relances se déclenchent automatiquement après la période définie
- Elles utilisent le template correspondant
- Modifiable dans le futur (bouton "✏️")

---

### 5️⃣ 📊 **STATISTIQUES**

Suivez vos KPIs en temps réel.

#### **Métriques affichées:**

- **Total leads**: Nombre total de prospects
- **Envoyés**: Messages envoyés avec succès
- **En attente**: Messages en attente de traitement
- **RDV proposés**: Prospects intéressés
- **RDV confirmés**: Rendez-vous validés
- **Clos**: Leads traités/terminés

#### **Utilisation:**

1. Cliquez sur "📊 Statistiques"
2. Les chiffres se rechargent automatiquement
3. Utile pour suivre votre progression

---

## 🔧 Conseils d'Utilisation

### ✅ Bonnes pratiques

1. **Avant de lancer une campagne:**
   - Testez avec le mode "Mode test" activé
   - Vérifiez l'aperçu du message
   - Vérifiez le nombre de leads à traiter

2. **Personnaliser vos messages:**
   - Utilisez les variables pour personnalisation
   - Testez différents templates
   - Mesurez les résultats avec les stats

3. **Gérer vos conversations:**
   - Répondez rapidement aux prospects
   - Notez les objections
   - Progammez les relances manuelles

4. **Mettre à jour vos templates:**
   - Améliorez-les régulièrement
   - Basez-vous sur ce qui fonctionne
   - Testez de nouveaux angles

### ❌ À éviter

- ❌ Envoyer des messages vides (validation empêche ça)
- ❌ Lancer sans vérifier l'aperçu
- ❌ Négliger le suivi des conversations
- ❌ Oublier de tester avant le vrai envoi (utilisez le mode test)

---

## 🚨 Messages d'Erreur et Solutions

| Message | Cause | Solution |
|---------|-------|----------|
| "❌ Écrivez un message avant de lancer !" | Message vide | Tapez un message ou chargez un template |
| "❌ Aucun lead ajouté !" | Aucun lead dans la liste | Ajoutez au moins un lead |
| "⚠️ Prénom, Nom et Téléphone sont obligatoires" | Champs manquants | Remplissez tous les champs * |
| "❌ Erreur: [message API]" | Problème serveur | Vérifiez la connexion, réessayez |

---

## 💡 Cas d'Usage Typiques

### Cas 1: Prospection Nouvelle

```
1. Ajoutez 10 leads (nom, téléphone, ville)
2. Choisissez le template "Initial"
3. Activez le mode test
4. Lancez pour vérifier
5. Lancez sans le mode test pour vrai envoi
6. Suivez les stats
```

### Cas 2: Relance Après 24h

```
1. Allez dans Templates
2. Modifiez "Relance 24h" si besoin
3. Les relances se déclenchent automatiquement
4. Ou lancez manuellement depuis Campagnes
```

### Cas 3: Gestion Active de Conversations

```
1. Allez dans Conversations
2. Sélectionnez un prospect
3. Lisez l'historique
4. Répondez au message
5. Planifiez un RDV
```

---

## 📱 Version Mobile

Le dashboard s'adapte aux petits écrans:

- Menus: Navigation reste accessible (sidebar)
- Layout: Passe de 2 colonnes à 1 colonne
- Formulaires: Toujours visibles et utilisables
- Boutons: Plus grands pour tactile

---

## 🔐 Sécurité & Confidentialité

- ✅ Tous les données restent dans votre navigateur (sauf lors de l'envoi API)
- ✅ Pas de cookies non-essentiels
- ✅ HTTPS recommandé en production
- ✅ Authentification à configurer au niveau backend

---

## ⚙️ Configuration Technique

**Serveur API requis:** `http://localhost:5000/api`

**Endpoints nécessaires:**
- `POST /api/campaign/launch` - Lancer campagne
- `GET /api/stats` - Charger stats
- `GET /api/templates/{key}/preview` - Charger template
- `GET /api/conversations` - Charger conversations (optionnel)

---

## 📞 Support

- Vérifiez que le serveur API est démarré
- Vérifiez la connexion internet
- Videz le cache du navigateur (Ctrl+Shift+Del)
- Consultez la console (F12 → Console) pour les erreurs

---

**Version**: 1.0  
**Dernière mise à jour**: Mars 2025  
**Status**: ✅ Production Ready
