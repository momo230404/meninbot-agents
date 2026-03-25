# 🔌 Guide d'Intégration - Dashboard Leads VIANOVA

## 📚 Table des matières
1. [Démarrage rapide](#-démarrage-rapide)
2. [Architecture](#-architecture)
3. [Intégration backend](#-intégration-backend)
4. [Tests des endpoints](#-tests-des-endpoints)
5. [Déploiement](#-déploiement)
6. [Troubleshooting](#-troubleshooting)

---

## 🚀 Démarrage Rapide

### Option 1: Tester avec le backend exemple (Flask)

#### 1. Installer les dépendances
```bash
pip install flask flask-cors
```

#### 2. Lancer le serveur
```bash
python /data/.openclaw/workspace/vianova-agent/BACKEND_EXAMPLE.py
```

**Output attendu** :
```
🚀 VIANOVA Leads Dashboard API
📍 Running on http://localhost:5000
💡 Visit http://localhost:5000/api/health to test
✅ Loaded 2 example leads
```

#### 3. Ouvrir le dashboard
```
http://localhost:8000/dashboard.html
```
(ou adaptez le port selon votre serveur)

#### 4. Tester
- Vérifiez que les 2 leads exemple s'affichent
- Essayez d'ajouter un lead
- Testez l'import CSV
- Lancez une campagne test

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────┐
│   Dashboard HTML (Frontend)             │
│   - Table des leads avec tri/filtre      │
│   - Formulaires modal                    │
│   - Import CSV                           │
│   - Aperçu campagnes                     │
└────────────┬────────────────────────────┘
             │ (Fetch API / JSON)
             │
    ┌────────▼──────────┐
    │  REST API         │
    │  (http://localhost:5000)
    └────────┬──────────┘
             │
    ┌────────▼──────────────────────┐
    │  Backend Implementation       │
    │  - Flask, Node, Python, etc.  │
    │  - Logique métier              │
    │  - Routage des API            │
    └────────┬──────────────────────┘
             │
    ┌────────▼──────────────────────┐
    │  Base de Données              │
    │  - PostgreSQL / MySQL / SQLite│
    │  - Storage des leads          │
    │  - Historique des campagnes   │
    └───────────────────────────────┘
```

---

## 🔗 Intégration Backend

### Pour Node.js / Express

```javascript
// backend.js
const express = require('express');
const cors = require('cors');
const app = express();

app.use(cors());
app.use(express.json());

const leads = [];
let leadId = 0;

// GET /api/leads
app.get('/api/leads', (req, res) => {
    res.json({ success: true, leads });
});

// POST /api/leads
app.post('/api/leads', (req, res) => {
    const { nom, prenom, telephone, ville, etat } = req.body;
    
    if (!nom || !prenom || !telephone) {
        return res.status(400).json({ 
            success: false, 
            message: 'nom, prenom, telephone required' 
        });
    }
    
    const lead = {
        id: leadId++,
        nom, prenom, telephone, ville,
        etat: etat || 'initial',
        created_at: new Date().toISOString()
    };
    
    leads.push(lead);
    res.status(201).json({ success: true, lead });
});

// PUT /api/leads/:id
app.put('/api/leads/:id', (req, res) => {
    const lead = leads.find(l => l.id == req.params.id);
    if (!lead) {
        return res.status(404).json({ success: false, message: 'Lead not found' });
    }
    
    Object.assign(lead, req.body);
    res.json({ success: true, lead });
});

// DELETE /api/leads/:id
app.delete('/api/leads/:id', (req, res) => {
    const idx = leads.findIndex(l => l.id == req.params.id);
    if (idx === -1) {
        return res.status(404).json({ success: false, message: 'Lead not found' });
    }
    
    leads.splice(idx, 1);
    res.json({ success: true, message: 'Lead deleted' });
});

app.listen(5000, () => console.log('✅ API running on :5000'));
```

### Pour Python / Django

```python
# views.py
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
import json

@csrf_exempt
@require_http_methods(["GET"])
def list_leads(request):
    leads = Lead.objects.values()
    return JsonResponse({
        'success': True,
        'leads': list(leads)
    })

@csrf_exempt
@require_http_methods(["POST"])
def create_lead(request):
    data = json.loads(request.body)
    
    if not all(k in data for k in ['nom', 'prenom', 'telephone']):
        return JsonResponse({
            'success': False,
            'message': 'nom, prenom, telephone required'
        }, status=400)
    
    lead = Lead.objects.create(**data)
    return JsonResponse({
        'success': True,
        'lead': model_to_dict(lead)
    }, status=201)

# urls.py
urlpatterns = [
    path('api/leads/', list_leads, name='list_leads'),
    path('api/leads/', create_lead, name='create_lead'),
]
```

### Pour Python / FastAPI

```python
# main.py
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
)

class Lead(BaseModel):
    nom: str
    prenom: str
    telephone: str
    ville: str = ""
    etat: str = "initial"

leads_db = []
lead_counter = 0

@app.get("/api/leads")
async def get_leads():
    return {
        "success": True,
        "leads": leads_db
    }

@app.post("/api/leads")
async def create_lead(lead: Lead):
    global lead_counter
    new_lead = lead.dict()
    new_lead['id'] = lead_counter
    new_lead['created_at'] = datetime.now().isoformat()
    leads_db.append(new_lead)
    lead_counter += 1
    return {"success": True, "lead": new_lead}

@app.put("/api/leads/{lead_id}")
async def update_lead(lead_id: int, lead_data: dict):
    lead = next((l for l in leads_db if l['id'] == lead_id), None)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    lead.update(lead_data)
    return {"success": True, "lead": lead}

@app.delete("/api/leads/{lead_id}")
async def delete_lead(lead_id: int):
    global leads_db
    leads_db = [l for l in leads_db if l['id'] != lead_id]
    return {"success": True, "message": "Lead deleted"}
```

### Pour PHP / Laravel

```php
// LeadController.php
namespace App\Http\Controllers;

use App\Models\Lead;
use Illuminate\Http\Request;

class LeadController extends Controller
{
    public function index()
    {
        return response()->json([
            'success' => true,
            'leads' => Lead::all()
        ]);
    }

    public function store(Request $request)
    {
        $validated = $request->validate([
            'nom' => 'required',
            'prenom' => 'required',
            'telephone' => 'required',
        ]);

        $lead = Lead::create($validated);

        return response()->json([
            'success' => true,
            'lead' => $lead
        ], 201);
    }

    public function update(Request $request, Lead $lead)
    {
        $lead->update($request->all());
        return response()->json([
            'success' => true,
            'lead' => $lead
        ]);
    }

    public function destroy(Lead $lead)
    {
        $lead->delete();
        return response()->json([
            'success' => true,
            'message' => 'Lead deleted'
        ]);
    }
}

// routes/api.php
Route::apiResource('leads', LeadController::class);
```

---

## 🧪 Tests des Endpoints

### 1. Vérifier la santé de l'API
```bash
curl http://localhost:5000/api/health
```

**Response attendue** :
```json
{
  "status": "ok",
  "leads": 2,
  "campaigns": 0
}
```

### 2. Lister les leads
```bash
curl http://localhost:5000/api/leads
```

### 3. Ajouter un lead
```bash
curl -X POST http://localhost:5000/api/leads \
  -H "Content-Type: application/json" \
  -d '{
    "nom": "Durand",
    "prenom": "Sophie",
    "telephone": "+33645678901",
    "ville": "Toulouse",
    "etat": "initial"
  }'
```

### 4. Éditer un lead
```bash
curl -X PUT http://localhost:5000/api/leads/0 \
  -H "Content-Type: application/json" \
  -d '{
    "etat": "rdv_propose",
    "date_dernier_contact": "2024-03-15"
  }'
```

### 5. Supprimer un lead
```bash
curl -X DELETE http://localhost:5000/api/leads/0
```

### 6. Importer des leads
```bash
curl -X POST http://localhost:5000/api/leads/import \
  -H "Content-Type: application/json" \
  -d '{
    "leads": [
      {
        "nom": "Lemoine",
        "prenom": "Luc",
        "telephone": "+33656789012",
        "ville": "Bordeaux",
        "etat": "initial"
      }
    ]
  }'
```

### 7. Lancer une campagne
```bash
curl -X POST http://localhost:5000/api/campaign/launch \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Bonjour {prenom}, test de campagne",
    "batch_size": 10,
    "dry_run": true,
    "leads": [
      {
        "id": 0,
        "nom": "Dupont",
        "prenom": "Jean",
        "telephone": "+33612345678"
      }
    ]
  }'
```

### Avec Postman
1. Ouvrir Postman
2. Créer une collection "VIANOVA"
3. Ajouter les requêtes GET, POST, PUT, DELETE sur `/api/leads`
4. Tester chaque endpoint

---

## 📦 Déploiement

### Option 1: Déploiement local (développement)
```bash
# Terminal 1: Lancer le backend
python BACKEND_EXAMPLE.py

# Terminal 2: Servir le frontend (Python)
python -m http.server 8000

# Accéder au dashboard
http://localhost:8000/dashboard.html
```

### Option 2: Déploiement sur Heroku

#### Créer un Procfile
```
web: gunicorn app:app
```

#### Installer gunicorn
```bash
pip install gunicorn
pip freeze > requirements.txt
```

#### Déployer
```bash
heroku login
heroku create my-vianova-api
git push heroku main
```

### Option 3: Déploiement Docker

#### Créer un Dockerfile
```dockerfile
FROM python:3.9
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
EXPOSE 5000
CMD ["python", "app.py"]
```

#### Build et run
```bash
docker build -t vianova-api .
docker run -p 5000:5000 vianova-api
```

### Option 4: Déploiement en production (recommandé)

#### Architecture suggérée :
```
┌─ Nginx (reverse proxy)
│  │
│  ├─ Frontend (HTML/CSS/JS) → Serveur statique
│  │
│  └─ Backend API (Flask/Node/etc) → Serveur app
│
└─ PostgreSQL/MySQL (Base de données)
```

#### Nginx config exemple
```nginx
server {
    listen 80;
    server_name api.vianova.com;

    # Frontend
    location / {
        root /var/www/vianova/frontend;
        try_files $uri $uri/ /dashboard.html;
    }

    # API
    location /api/ {
        proxy_pass http://localhost:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

---

## 🔧 Configuration

### Changer le domaine/port de l'API

#### Dans le dashboard (dashboard.html)
```javascript
// Ligne ~6 du script
const API_URL = 'https://api.vianova.com'; // ou http://localhost:5000
```

### CORS (si API sur domaine différent)

#### Flask
```python
CORS(app, resources={
    r"/api/*": {
        "origins": ["https://dashboard.vianova.com"],
        "methods": ["GET", "POST", "PUT", "DELETE"],
        "allow_headers": ["Content-Type"]
    }
})
```

#### Express
```javascript
const cors = require('cors');
app.use(cors({
    origin: 'https://dashboard.vianova.com',
    methods: ['GET', 'POST', 'PUT', 'DELETE']
}));
```

---

## 🐛 Troubleshooting

### Problème: "Failed to fetch from API"

**Cause** : API non accessible  
**Solution** :
```bash
# Vérifier que l'API est actif
curl http://localhost:5000/api/health

# Vérifier les logs du serveur API
# (vérifier les erreurs côté backend)
```

### Problème: "CORS error"

**Cause** : Frontend et API sur domaines différents  
**Solution** : 
```python
# Dans backend : activer CORS
from flask_cors import CORS
CORS(app)
```

### Problème: "CSV ne s'importe pas"

**Cause** : Format CSV incorrect  
**Solution** :
```
✅ Colonnes requises: nom, prenom, telephone
✅ Séparation: virgules (,)
✅ Encodage: UTF-8
❌ Ne pas: Mélanger les séparateurs
```

### Problème: "Les leads ne s'affichent pas"

**Cause** : JSON malformé de l'API  
**Solution** :
```bash
# Tester l'API directement
curl http://localhost:5000/api/leads

# Vérifier que la response est bien :
# {
#   "success": true,
#   "leads": [ ... ]
# }
```

### Problème: "Modal ne s'ouvre pas"

**Cause** : Erreur JavaScript  
**Solution** :
```javascript
// Ouvrir DevTools (F12) → Console
// Vérifier les erreurs
// Vérifier la variable currentEditingLeadId
```

---

## ✅ Checklist Intégration

### Backend Setup
- [ ] Environnement de développement configuré
- [ ] Dépendances installées (Flask/Express/etc)
- [ ] Base de données configurée
- [ ] CORS activé
- [ ] Serveur API lancé et accessible

### Endpoints
- [ ] GET /api/leads
- [ ] POST /api/leads
- [ ] PUT /api/leads/{id}
- [ ] DELETE /api/leads/{id}
- [ ] POST /api/leads/import
- [ ] POST /api/campaign/launch
- [ ] GET /api/stats
- [ ] POST /api/templates/{key}
- [ ] GET /api/templates/{key}/preview

### Frontend
- [ ] dashboard.html en place
- [ ] API_URL correctement configurée
- [ ] Tous les boutons fonctionnent
- [ ] Tableaux affichent les données
- [ ] Modals s'ouvrent/ferment
- [ ] Tri et filtre fonctionnent

### Tests
- [ ] Ajouter un lead manuellement
- [ ] Importer un CSV
- [ ] Éditer un lead
- [ ] Supprimer un lead
- [ ] Mettre à jour dernier contact
- [ ] Lancer une campagne (test)
- [ ] Sauvegarde d'un template
- [ ] Consulter les statistiques

### Données
- [ ] Données persistent après refresh
- [ ] Formatage des dates correct
- [ ] États affichent correctement
- [ ] Recherche/filtre fonctionne

### Sécurité
- [ ] Validation des inputs frontend
- [ ] Validation des inputs backend
- [ ] Gestion des erreurs
- [ ] Aucune donnée sensible en logs
- [ ] HTTPS en production (si applicable)

---

## 📞 Support & Ressources

### Documentation
- [LEADS_DASHBOARD_README.md](./LEADS_DASHBOARD_README.md) - Guide complet du dashboard
- [BACKEND_EXAMPLE.py](./BACKEND_EXAMPLE.py) - Exemple backend Flask
- Ce fichier - Guide d'intégration

### Exemples de code
- **Frontend** : dashboard.html inclus
- **Backend** : 4 exemples (Flask, Node, Django, FastAPI, PHP)
- **Tests** : Commandes curl provided

### Frameworks recommandés
- **Backend léger** : Flask, Express
- **Backend robuste** : Django, FastAPI
- **Base de données** : PostgreSQL (recommandé), MySQL, SQLite (dev)
- **Hosting** : Heroku, AWS, DigitalOcean, Render

---

**Version** : 1.0  
**Dernière mise à jour** : Mars 2024
