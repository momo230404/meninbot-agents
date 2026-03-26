#!/usr/bin/env python3
"""API Flask pour le dashboard Vianova - PRODUCTION"""
import json
import logging
import re
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Any
import os
import sys

from flask import Flask, jsonify, request, send_file, session, redirect, url_for
from werkzeug.security import generate_password_hash, check_password_hash
from flask_cors import CORS
from redis_client import RedisClient
from leads_manager import LeadsManager
from tools.sheets import GoogleSheetsClient  # Optionnel pour exports
from tools.evolution import EvolutionAPI
from tools.miizy_api import MiizyAPI
from templates_api import MessageTemplates

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('logs/dashboard_api.log')
    ]
)
logger = logging.getLogger(__name__)

# Configuration
CONFIG_FILE = 'config.json'
if not os.path.exists(CONFIG_FILE):
    logger.error(f"{CONFIG_FILE} not found")
    sys.exit(1)

with open(CONFIG_FILE, 'r') as f:
    CONFIG = json.load(f)

# Initialize clients
try:
    redis_client = RedisClient(CONFIG['redis']['url'])
    logger.info("✅ Redis connecté")
except Exception as e:
    logger.error(f"❌ Redis erreur: {e}")
    sys.exit(1)

# Initialize LeadsManager (stockage principal)
try:
    leads_json_file = CONFIG.get('leads_json_file', 'leads.json')
    leads_manager = LeadsManager(redis_client, leads_json_file)
    
    # Charger les leads depuis JSON local au démarrage
    if os.path.exists(leads_json_file):
        leads_manager.save_leads_from_json()
        logger.info("✅ Leads chargés depuis JSON local")
    
    logger.info("✅ LeadsManager initialisé")
except Exception as e:
    logger.error(f"❌ LeadsManager erreur: {e}")
    sys.exit(1)

# Google Sheets optionnel (pour exports)
try:
    sheets_client = GoogleSheetsClient(
        CONFIG['google']['credentials_file'],
        CONFIG['google']['sheets_id']
    )
    logger.info("✅ Google Sheets connecté (optionnel)")
    sheets_available = True
except Exception as e:
    logger.warning(f"⚠️  Google Sheets non disponible: {e}")
    sheets_client = None
    sheets_available = False

try:
    evolution_api = EvolutionAPI(
        CONFIG['evolution_api']['api_key'],
        CONFIG['evolution_api']['base_url'],
        CONFIG['evolution_api']['instance_name']
    )
    logger.info("✅ Evolution API Vianova connecté")
except Exception as e:
    logger.error(f"❌ Evolution API erreur: {e}")
    sys.exit(1)

# ── Ressources Miizy Agent ──────────────────────────────────────────────────
_miizy_evo_cfg = CONFIG.get('miizy_evolution_api', CONFIG['evolution_api'])
try:
    miizy_evolution_api = EvolutionAPI(
        _miizy_evo_cfg['api_key'],
        _miizy_evo_cfg['base_url'],
        _miizy_evo_cfg['instance_name']
    )
    logger.info("✅ Evolution API Miizy connecté")
except Exception as e:
    logger.warning(f"⚠️  Evolution API Miizy non disponible: {e}")
    miizy_evolution_api = evolution_api  # fallback

# ── Instances Evolution par commercial Miizy ────────────────────────────────
_miizy_commercial_evo: Dict[str, Any] = {}        # {commercial_id: EvolutionAPI}
_miizy_instance_to_commercial: Dict[str, str] = {} # {instance_name_lower: commercial_id}

for _comm_id, _comm_cfg in CONFIG.get('miizy_commerciaux', {}).items():
    try:
        _evo_inst = EvolutionAPI(
            _comm_cfg['api_key'],
            _comm_cfg['base_url'],
            _comm_cfg['instance_name'],
        )
        _miizy_commercial_evo[_comm_id] = _evo_inst
        _miizy_instance_to_commercial[_comm_cfg['instance_name'].lower()] = _comm_id
        logger.info(f"✅ Commercial Miizy '{_comm_id}' ({_comm_cfg['instance_name']}) prêt")
    except Exception as _e:
        logger.warning(f"⚠️  Commercial Miizy '{_comm_id}' erreur: {_e}")

# Fallback : Adam pointe sur miizy_evolution_api si absent de config
if 'adam' not in _miizy_commercial_evo:
    _miizy_commercial_evo['adam'] = miizy_evolution_api
    _miizy_instance_to_commercial[_miizy_evo_cfg['instance_name'].lower()] = 'adam'


def _get_commercial_evo(commercial_id: str):
    """Retourne l'instance Evolution du commercial (fallback : Adam)."""
    return _miizy_commercial_evo.get(commercial_id or 'adam', miizy_evolution_api)


def _instance_name_to_commercial(instance_name: str) -> str:
    """Identifie le commercial_id depuis le nom d'instance Evolution."""
    return _miizy_instance_to_commercial.get((instance_name or '').lower(), 'adam')


def _get_session_commercial_id():
    """Retourne le commercial_id du user connecté, ou None si admin."""
    try:
        users = _load_users()
        email = session.get('user_email', '')
        return users.get(email, {}).get('commercial_id')
    except Exception:
        return None

_miizy_leads_file = CONFIG.get('miizy', {}).get('leads_json_file', 'miizy_leads.json')
try:
    # Initialiser miizy_leads.json si vide ou invalide
    if not os.path.exists(_miizy_leads_file) or os.path.getsize(_miizy_leads_file) == 0:
        with open(_miizy_leads_file, 'w', encoding='utf-8') as _f:
            json.dump({'leads': [], 'count': 0}, _f)
    miizy_leads_manager = LeadsManager(redis_client, _miizy_leads_file, prefix="miizy:lead:")
    miizy_leads_manager.save_leads_from_json()
    logger.info("✅ Miizy LeadsManager initialisé (prefix=miizy:lead:)")
except Exception as e:
    logger.warning(f"⚠️  Miizy LeadsManager erreur: {e}")
    miizy_leads_manager = leads_manager  # fallback

# Proxy agent : route automatiquement vers Vianova ou Miizy selon le chemin de la requête
class _AgentProxy:
    """Proxy transparent : utilise les ressources Vianova ou Miizy selon request.path."""
    def __init__(self, vianova_obj, miizy_obj):
        object.__setattr__(self, '_v', vianova_obj)
        object.__setattr__(self, '_m', miizy_obj)
    def _obj(self):
        try:
            from flask import request, has_request_context
            if has_request_context() and '/miizy/' in request.path:
                return object.__getattribute__(self, '_m')
        except Exception:
            pass
        return object.__getattribute__(self, '_v')
    def __getattr__(self, name):
        return getattr(self._obj(), name)
    def __call__(self, *a, **kw):
        return self._obj()(*a, **kw)

_vianova_leads_manager = leads_manager
_vianova_evolution_api = evolution_api
leads_manager = _AgentProxy(_vianova_leads_manager, miizy_leads_manager)
evolution_api = _AgentProxy(_vianova_evolution_api, miizy_evolution_api)

try:
    miizy_api = MiizyAPI(
        CONFIG['vianova']['api_key'],
        CONFIG['vianova']['api_base_url']
    )
    logger.info("✅ Miizy API connecté")
except Exception as e:
    logger.error(f"❌ Miizy API erreur: {e}")
    sys.exit(1)

app = Flask(__name__, static_folder='.', static_url_path='')
app.secret_key = 'vianova_secret_key_2026_xK9mP3qR'
CORS(app)

# ==================== UTILISATEURS ====================
USERS_FILE = '/data/.openclaw/workspace/vianova-agent/users.json'

def _load_users():
    """Charge les utilisateurs depuis users.json"""
    try:
        if os.path.exists(USERS_FILE):
            with open(USERS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Erreur chargement users.json: {e}")
    # Fallback : utilisateurs par défaut si le fichier n'existe pas encore
    return {
        'ddejesus@vianova-groupe.fr': {
            'name': 'Daniel De Jesus',
            'password_hash': generate_password_hash('Danielvianova123@'),
            'role': 'daniel',
            'agent': 'vianova',
            'redirect': '/?agent=vianova',
        },
        'admin@vianova.meninbot.com': {
            'name': 'Admin',
            'password_hash': generate_password_hash('AdminVianova2026!'),
            'role': 'admin',
            'agent': 'all',
            'redirect': '/',
        },
    }

def _save_users(users):
    """Sauvegarde les utilisateurs dans users.json"""
    try:
        with open(USERS_FILE, 'w', encoding='utf-8') as f:
            json.dump(users, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Erreur sauvegarde users.json: {e}")


def _is_miizy_commercial_role(role: str) -> bool:
    """Retourne True si le rôle est un commercial Miizy (accès limité)."""
    return role in ('miizy_commercial', 'mohamed', 'dorian')

# ==================== ÉTATS ====================
STATE_TRANSITIONS = {
    "initial": "message_a_envoyer",
    "message_a_envoyer": "en_cours",
    "en_cours": "rdv_propose",
    "rdv_propose": "rdv_confirme",
    "rdv_confirme": "clos",
    "relance": "en_cours",
    "clos": "clos"
}

# ==================== HELPERS ====================

def should_relance(lead: Dict[str, Any]) -> bool:
    """Vérifie si une relance est nécessaire"""
    state = lead.get("state", "initial")
    last_msg_at = lead.get("last_message_at")
    
    if state == "clos" or state == "rdv_confirme":
        return False
    
    if not last_msg_at:
        return False
    
    try:
        last_msg_time = datetime.fromisoformat(last_msg_at)
    except:
        return False
    
    now = datetime.now()
    hours_since = (now - last_msg_time).total_seconds() / 3600
    
    # Relance après 24h sans réponse ou après 6h si réponse partielle
    if state == "en_cours" and hours_since > 24:
        return True
    if state == "rdv_propose" and hours_since > 6:
        return True
    
    return False

def update_lead_state(phone: str, new_state: str):
    """Mets à jour l'état d'un lead"""
    leads_manager.set_state(phone, new_state)
    logger.info(f"🔄 État mis à jour: {phone} → {new_state}")

# ==================== API ROUTES ====================

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Page de connexion"""
    if request.method == 'POST':
        email = (request.form.get('email') or '').strip().lower()
        password = request.form.get('password') or ''
        users = _load_users()
        user = users.get(email)
        if user and check_password_hash(user['password_hash'], password):
            session['user_email'] = email
            session['user_role'] = user['role']
            session['user_name'] = user.get('name', email)
            session['user_agent'] = user.get('agent', 'vianova')
            return redirect(user['redirect'])
        return _login_page(error='Email ou mot de passe incorrect')
    return _login_page()

@app.route('/logout', methods=['GET', 'POST'])
def logout():
    session.clear()
    return redirect('/login')

def _login_page(error=None):
    error_html = f'<div style="background:#fff5f5;border:1px solid #fed7d7;color:#c53030;padding:12px 16px;border-radius:10px;font-size:14px;margin-bottom:20px;text-align:center;">⚠️ {error}</div>' if error else ''
    return f'''<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Connexion — Vianova Dashboard</title>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{
    min-height: 100vh;
    background: linear-gradient(135deg, #0f3460 0%, #0099ff 50%, #00c6a2 100%);
    display: flex; align-items: center; justify-content: center;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  }}
  .card {{
    background: white;
    border-radius: 24px;
    padding: 48px 44px;
    width: 100%;
    max-width: 420px;
    box-shadow: 0 32px 80px rgba(0,0,0,0.25);
    animation: fadeUp 0.4s ease;
  }}
  @keyframes fadeUp {{
    from {{ opacity:0; transform:translateY(20px); }}
    to   {{ opacity:1; transform:translateY(0); }}
  }}
  .logo {{
    text-align: center;
    margin-bottom: 32px;
  }}
  .logo-icon {{
    width: 72px; height: 72px;
    background: linear-gradient(135deg, #0f3460, #0099ff);
    border-radius: 20px;
    display: inline-flex; align-items: center; justify-content: center;
    font-size: 32px; margin-bottom: 16px;
    box-shadow: 0 8px 24px rgba(0,153,255,0.35);
  }}
  .logo h1 {{ font-size: 22px; font-weight: 800; color: #0f3460; margin-bottom: 4px; }}
  .logo p {{ font-size: 13px; color: #718096; }}
  label {{
    display: block;
    font-size: 13px; font-weight: 600; color: #2d3748;
    margin-bottom: 6px;
  }}
  input {{
    width: 100%;
    padding: 13px 16px;
    border: 2px solid #e2e8f0;
    border-radius: 12px;
    font-size: 14px;
    outline: none;
    transition: border-color 0.2s, box-shadow 0.2s;
    margin-bottom: 18px;
    color: #1a202c;
  }}
  input:focus {{
    border-color: #0099ff;
    box-shadow: 0 0 0 3px rgba(0,153,255,0.15);
  }}
  button {{
    width: 100%;
    padding: 14px;
    background: linear-gradient(135deg, #0f3460, #0099ff);
    color: white;
    border: none;
    border-radius: 12px;
    font-size: 15px;
    font-weight: 700;
    cursor: pointer;
    transition: opacity 0.2s, transform 0.1s;
    margin-top: 4px;
    letter-spacing: 0.3px;
  }}
  button:hover {{ opacity: 0.92; transform: translateY(-1px); }}
  button:active {{ transform: translateY(0); }}
  .footer {{ text-align:center; margin-top:24px; font-size:12px; color:#a0aec0; }}
</style>
</head>
<body>
<div class="card">
  <div class="logo">
    <div class="logo-icon">⚡</div>
    <h1>Vianova Dashboard</h1>
    <p>Connectez-vous pour accéder à votre espace</p>
  </div>
  {error_html}
  <form method="POST" action="/login">
    <label for="email">Adresse email</label>
    <input type="email" id="email" name="email" placeholder="votre@email.com" required autocomplete="email">
    <label for="password">Mot de passe</label>
    <input type="password" id="password" name="password" placeholder="••••••••••••" required autocomplete="current-password">
    <button type="submit">Se connecter →</button>
  </form>
  <div class="footer">Vianova — Agent WhatsApp IA &nbsp;•&nbsp; Accès sécurisé</div>
</div>
</body>
</html>'''

@app.route('/', methods=['GET'])
def serve_dashboard():
    """Serve the dashboard — protégé par session"""
    if not session.get('user_email'):
        return redirect('/login')
    resp = send_file('dashboard.html', mimetype='text/html')
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate'
    resp.headers['Pragma'] = 'no-cache'
    return resp

@app.route('/dashboard', methods=['GET'])
def serve_dashboard_alt():
    """Serve the dashboard (alternate route)"""
    if not session.get('user_email'):
        return redirect('/login')
    resp = send_file('dashboard.html', mimetype='text/html')
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate'
    resp.headers['Pragma'] = 'no-cache'
    return resp

@app.route('/api/auth/me', methods=['GET'])
def auth_me():
    """Retourne les informations de l'utilisateur connecté"""
    if not session.get('user_email'):
        return jsonify({"error": "Not authenticated"}), 401
    return jsonify({
        "email": session.get('user_email'),
        "name": session.get('user_name', session.get('user_email')),
        "role": session.get('user_role'),
        "agent": session.get('user_agent', 'vianova'),
    })


# ==================== ADMIN ROUTES ====================

@app.route('/api/admin/users', methods=['GET'])
def admin_get_users():
    """Retourne la liste des utilisateurs filtrés par agent — admin seulement"""
    if session.get('user_role') != 'admin':
        return jsonify({"error": "Forbidden"}), 403
    users = _load_users()
    agent_filter = request.args.get('agent')  # 'miizy' ou 'vianova'
    result = []
    for email, data in users.items():
        agent = data.get("agent", "vianova")
        # Filtrer par agent si demandé (admin@miizy = agent 'all' → toujours inclus)
        if agent_filter and agent != 'all' and agent != agent_filter:
            continue
        result.append({
            "email": email,
            "name": data.get("name", email),
            "role": data.get("role", "agent_user"),
            "agent": agent,
            "redirect": data.get("redirect", "/"),
        })
    return jsonify({"success": True, "users": result})


@app.route('/api/admin/users', methods=['POST'])
def admin_create_user():
    """Crée un nouvel utilisateur — admin seulement"""
    if session.get('user_role') != 'admin':
        return jsonify({"error": "Forbidden"}), 403
    data = request.get_json(force=True) or {}
    email = (data.get("email") or "").strip().lower()
    name = (data.get("name") or "").strip()
    password = data.get("password") or ""
    role = data.get("role") or "agent_user"
    agent = data.get("agent") or "vianova"

    if not email or not password:
        return jsonify({"success": False, "error": "email et password obligatoires"}), 400

    users = _load_users()
    if email in users:
        return jsonify({"success": False, "error": "Cet email existe déjà"}), 400

    # Calculer le redirect selon l'agent
    if agent == "vianova":
        redirect_url = "/?agent=vianova"
    elif agent == "miizy":
        redirect_url = "/?agent=miizy"
    else:
        redirect_url = "/"

    users[email] = {
        "name": name or email,
        "password_hash": generate_password_hash(password),
        "role": role,
        "agent": agent,
        "redirect": redirect_url,
    }
    _save_users(users)
    logger.info(f"[admin] Compte créé : {email} (role={role}, agent={agent})")
    return jsonify({"success": True, "email": email}), 201


@app.route('/api/admin/users/<path:email>', methods=['DELETE'])
def admin_delete_user(email):
    """Supprime un utilisateur — admin seulement, ne peut pas se supprimer soi-même"""
    if session.get('user_role') != 'admin':
        return jsonify({"error": "Forbidden"}), 403
    if email == session.get('user_email'):
        return jsonify({"success": False, "error": "Vous ne pouvez pas supprimer votre propre compte"}), 400
    users = _load_users()
    if email not in users:
        return jsonify({"success": False, "error": "Utilisateur non trouvé"}), 404
    del users[email]
    _save_users(users)
    logger.info(f"[admin] Compte supprimé : {email}")
    return jsonify({"success": True})


@app.route('/api/admin/users/<path:email>', methods=['PUT'])
def admin_update_user(email):
    """Met à jour un utilisateur (name, password, agent) — admin seulement"""
    if session.get('user_role') != 'admin':
        return jsonify({"error": "Forbidden"}), 403
    users = _load_users()
    if email not in users:
        return jsonify({"success": False, "error": "Utilisateur non trouvé"}), 404
    data = request.get_json(force=True) or {}
    user = users[email]

    if data.get("name"):
        user["name"] = data["name"].strip()
    if data.get("password"):
        user["password_hash"] = generate_password_hash(data["password"])
    if data.get("agent"):
        agent = data["agent"]
        user["agent"] = agent
        if agent == "vianova":
            user["redirect"] = "/?agent=vianova"
        elif agent == "miizy":
            user["redirect"] = "/?agent=miizy"
        else:
            user["redirect"] = "/"
    if "role" in data:
        user["role"] = data["role"]

    users[email] = user
    _save_users(users)
    logger.info(f"[admin] Compte mis à jour : {email}")
    return jsonify({"success": True})


@app.route('/api/health', methods=['GET'])
def health():
    """Health check"""
    return jsonify({
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "services": {
            "redis": "connected",
            "sheets": "connected",
            "evolution": "connected",
            "miizy": "connected"
        }
    })

@app.route('/api/leads', methods=['GET'])
def get_leads():
    """Récupère tous les leads avec leurs états"""
    try:
        leads = leads_manager.list_leads()

        # Filtrage par commercial_id pour les comptes commerciaux Miizy
        _is_miizy_route = '/miizy/' in request.path
        if _is_miizy_route:
            _comm_id = _get_session_commercial_id()
            if _comm_id:  # commercial → voit uniquement ses leads
                leads = [l for l in leads if l.get('commercial_id', '') == _comm_id]

        # Filtrage par commercial_id demandé explicitement (admin qui filtre)
        _filter_comm = request.args.get('commercial_id')
        if _filter_comm and not _get_session_commercial_id():
            leads = [l for l in leads if l.get('commercial_id', '') == _filter_comm]

        # Ajouter info relance
        enriched_leads = []
        for lead in leads:
            enriched_leads.append({
                **lead,
                "needs_relance": should_relance(lead)
            })

        return jsonify({
            "success": True,
            "count": len(enriched_leads),
            "leads": enriched_leads
        })
    except Exception as e:
        logger.error(f"Error getting leads: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/leads', methods=['POST'])
def add_lead():
    """Ajoute un nouveau lead"""
    try:
        data = request.json
        
        # Validation des champs obligatoires
        required_fields = ['phone', 'nom', 'prenom']
        for field in required_fields:
            if not data.get(field):
                return jsonify({"success": False, "error": f"Champ obligatoire manquant: {field}"}), 400
        
        # Préparer les données du lead
        lead_data = {
            'phone': data.get('phone', ''),
            'telephone': data.get('phone', ''),
            'nom': data.get('nom', ''),
            'prenom': data.get('prenom', ''),
            'ville': data.get('ville', ''),
            'typologie': data.get('typologie', ''),
            'budget': data.get('budget', ''),
            'date_dernier_contact': data.get('date_dernier_contact', ''),
            'date_envoi': data.get('date_envoi', ''),
            'etat': data.get('etat', data.get('state', 'initial')),
            'state': data.get('etat', data.get('state', 'initial')),
            'ai_enabled': data.get('ai_enabled', True),
            'source': data.get('source', 'api'),
        }
        if data.get('commercial_id'):
            lead_data['commercial_id'] = data['commercial_id']
        
        # Ajouter dans Redis
        phone = lead_data['phone']
        if not leads_manager.add_lead(lead_data):
            return jsonify({"success": False, "error": "Erreur ajout lead"}), 400
        
        logger.info(f"✅ Lead ajouté: {phone}")
        
        return jsonify({
            "success": True,
            "message": f"Lead {lead_data['prenom']} {lead_data['nom']} ajouté",
            "phone": phone
        }), 201
    
    except Exception as e:
        logger.error(f"Error adding lead: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

def _normalize_typo(typo: str) -> str:
    """Convertit T1→'1 pièce', T2→'2 pièces', F3→'3 pièces', etc."""
    if not typo:
        return typo
    import re as _re
    m = _re.match(r'^[TtFf]\s*([1-9])', typo.strip())
    if m:
        n = int(m.group(1))
        return '1 pièce' if n == 1 else f'{n} pièces'
    return typo  # studio, maison, villa → inchangé


_MOIS_FR = {
    'janvier': '01', 'février': '02', 'fevrier': '02', 'mars': '03',
    'avril': '04', 'mai': '05', 'juin': '06', 'juillet': '07',
    'août': '08', 'aout': '08', 'septembre': '09', 'octobre': '10',
    'novembre': '11', 'décembre': '12', 'decembre': '12'
}

def _parse_french_date(date_str: str) -> str:
    """Normalise une date en ISO (YYYY-MM-DD ou YYYY-MM-DDTHH:MM:00).
    Gère: '8 février 2026', '8 février 2026 14:37', '12-02-2026', '12-02-2026 14:37'
    Retourne la chaîne originale si non reconnue.
    """
    if not date_str:
        return date_str
    s = date_str.strip()
    # Format FR textuel : "8 février 2026" ou "8 février 2026 14:37"
    m = re.match(
        r'^(\d{1,2})\s+(\S+)\s+(\d{4})(?:\s+(\d{1,2}):(\d{2}))?$',
        s, re.IGNORECASE
    )
    if m:
        day, mois_raw, year, hh, mm = m.groups()
        import unicodedata
        mois_key_na = ''.join(
            c for c in unicodedata.normalize('NFD', mois_raw.lower())
            if unicodedata.category(c) != 'Mn'
        )
        num = _MOIS_FR.get(mois_raw.lower()) or _MOIS_FR.get(mois_key_na)
        if num:
            base = f"{year}-{num}-{int(day):02d}"
            if hh and mm:
                return f"{base}T{int(hh):02d}:{mm}:00"
            return base
    # Format DD-MM-YYYY ou DD/MM/YYYY avec heure optionnelle
    m2 = re.match(
        r'^(\d{1,2})[-/](\d{1,2})[-/](\d{4})(?:[T\s]+(\d{1,2}):(\d{2}))?',
        s
    )
    if m2:
        day, mon, year, hh, mm = m2.groups()
        base = f"{year}-{int(mon):02d}-{int(day):02d}"
        if hh and mm:
            return f"{base}T{int(hh):02d}:{mm}:00"
        return base
    return s  # déjà ISO ou format inconnu


@app.route('/api/leads/import', methods=['POST'])
def import_leads():
    """Import en masse de leads depuis le dashboard (CSV parsé côté client)."""
    try:
        data = request.json or {}
        leads_list = data.get('leads', [])
        if not leads_list:
            return jsonify({"success": False, "message": "Aucun lead dans la requête"}), 400

        imported = 0
        skipped = 0
        errors = []

        for item in leads_list:
            # Normaliser le téléphone (champ peut être telephone ou phone)
            tel = (item.get('telephone') or item.get('phone') or '').strip()
            if not tel:
                skipped += 1
                continue

            # Formatage numéro : 06XXXXXXXX → +336XXXXXXXX
            tel_clean = tel.replace(' ', '').replace('.', '').replace('-', '')
            if tel_clean.startswith('0') and len(tel_clean) == 10:
                tel_clean = '+33' + tel_clean[1:]
            elif tel_clean.startswith('33') and not tel_clean.startswith('+'):
                tel_clean = '+' + tel_clean
            elif not tel_clean.startswith('+'):
                tel_clean = '+33' + tel_clean

            # commercial_id : priorité à la valeur par item, sinon valeur globale du body
            _comm_id = item.get('commercial_id') or data.get('commercial_id') or ''
            lead_data = {
                'phone': tel_clean,
                'telephone': tel_clean,
                'nom': item.get('nom', ''),
                'prenom': item.get('prenom', ''),
                'ville': item.get('ville', ''),
                'typologie': _normalize_typo(item.get('typologie', '')),
                'budget': item.get('budget', ''),
                'date_dernier_contact': _parse_french_date(item.get('date_dernier_contact', '')),
                'date_envoi': _parse_french_date(item.get('date_envoi', '')),
                'etat': item.get('etat', 'initial'),
                'state': item.get('etat', 'initial'),
                'source': 'csv_import',
                'ai_enabled': True,
            }
            if _comm_id:
                lead_data['commercial_id'] = _comm_id

            try:
                leads_manager.add_lead(lead_data)
                imported += 1
            except Exception as _e:
                errors.append(tel_clean)
                logger.error(f"[import] erreur lead {tel_clean}: {_e}")

        logger.info(f"[import CSV] {imported} leads importés, {skipped} ignorés (sans téléphone)")
        return jsonify({
            "success": True,
            "imported": imported,
            "skipped": skipped,
            "errors": errors,
            "message": f"{imported} lead(s) importé(s) avec succès"
        })

    except Exception as e:
        logger.error(f"[import CSV] erreur globale: {e}")
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/api/leads/migrate-typo', methods=['POST'])
def migrate_typo():
    """Migre toutes les typologies existantes : T2 → 2 pièces, etc."""
    try:
        all_leads = leads_manager.list_leads()
        updated = 0
        for lead in all_leads:
            typo_raw = lead.get('typologie', '')
            typo_new = _normalize_typo(typo_raw)
            if typo_new != typo_raw:
                phone = lead.get('phone') or lead.get('telephone')
                if phone:
                    leads_manager.update_lead(phone, {'typologie': typo_new})
                    updated += 1
        logger.info(f"[migrate-typo] {updated} leads mis à jour")
        return jsonify({"success": True, "updated": updated,
                        "message": f"{updated} lead(s) mis à jour"})
    except Exception as e:
        logger.error(f"[migrate-typo] erreur: {e}")
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/api/leads/<phone>', methods=['PUT'])
def _normalize_phone(p: str) -> str:
    """Normalise un numéro vers sa forme canonique sans + ni espaces.
    Convertit le format local français 06/07 → 336/337.
    Ex: +33 6 12 34 56 78 → 33612345678
        0612345678        → 33612345678
        33612345678       → 33612345678
    """
    p = p.strip().replace('+', '').replace(' ', '').replace('-', '').replace('.', '')
    # Format local français : commence par 0 suivi d'un chiffre (10 chiffres)
    if len(p) == 10 and p.startswith('0'):
        p = '33' + p[1:]
    return p


def update_lead(phone):
    """Édite un lead existant"""
    try:
        data = request.json
        _is_miizy = '/miizy/' in request.path
        mgr = miizy_leads_manager if _is_miizy else leads_manager

        # Détecter un changement réel de numéro de téléphone
        new_phone_raw = (data.get('phone') or data.get('telephone') or '').strip()
        old_norm = _normalize_phone(phone)
        new_norm = _normalize_phone(new_phone_raw) if new_phone_raw else ''

        # Vrai changement = numéros normalisés différents
        if new_norm and new_norm != old_norm:
            old_lead = mgr.get_lead(phone)
            if not old_lead:
                return jsonify({"success": False, "error": "Lead non trouvé"}), 404
            old_lead.update(data)
            old_lead['phone'] = new_phone_raw
            old_lead['telephone'] = new_phone_raw
            mgr.delete_lead(phone)
            mgr.add_lead(old_lead)
            logger.info(f"✏️ Lead téléphone modifié: {phone} → {new_phone_raw}")
            return jsonify({"success": True, "message": "Lead mis à jour", "phone": new_phone_raw})

        # Même numéro (formats différents acceptés) → mise à jour classique
        # On garde le numéro saisi par l'utilisateur pour affichage
        if new_phone_raw:
            data['phone'] = new_phone_raw
            data['telephone'] = new_phone_raw
        if not mgr.update_lead(phone, data):
            return jsonify({"success": False, "error": "Lead non trouvé"}), 404

        if data.get('state'):
            update_lead_state(phone, data.get('state'))

        logger.info(f"✏️ Lead mis à jour: {phone}")
        return jsonify({"success": True, "message": "Lead mis à jour", "phone": phone})

    except Exception as e:
        logger.error(f"Error updating lead: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/leads/<phone>', methods=['DELETE'])
def delete_lead(phone):
    """Supprime un lead"""
    try:
        # Essayer avec le phone tel quel, puis sans le +, puis avec le +
        phone_variants = [phone]
        if phone.startswith('+'):
            phone_variants.append(phone[1:])
        else:
            phone_variants.append('+' + phone)

        deleted = False
        for p in phone_variants:
            if leads_manager.delete_lead(p):
                deleted = True
                phone = p
                break

        if not deleted:
            return jsonify({"success": False, "error": "Lead non trouvé"}), 404

        logger.info(f"🗑️ Lead supprimé: {phone}")

        return jsonify({
            "success": True,
            "message": "Lead supprimé",
            "phone": phone
        })

    except Exception as e:
        logger.error(f"Error deleting lead: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/leads/<phone>/messages', methods=['GET'])
def get_messages(phone):
    """Récupère l'historique de conversation"""
    try:
        messages = redis_client.get_messages(phone)
        return jsonify({
            "success": True,
            "phone": phone,
            "messages": messages or []
        })
    except Exception as e:
        logger.error(f"Error getting messages: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/leads/<phone>/message', methods=['POST'])
def send_message(phone):
    """Envoie un message manuel"""
    try:
        data = request.json
        # Accepte 'message', 'custom_message' (campagne) ou 'template' (bulk relance)
        message_text = data.get('message') or data.get('custom_message', '')
        template_key = data.get('template', '')
        lead = leads_manager.get_lead(phone) or {}
        # Fallback JSON si Redis indisponible
        if not lead:
            phone_clean = phone.lstrip('+')
            for l in leads_manager.load_from_json():
                lphone = (l.get('phone') or l.get('telephone') or '').lstrip('+')
                if lphone == phone_clean:
                    lead = l
                    break

        if not message_text and template_key:
            # Résoudre le template et personnaliser avec les données du lead
            tpl_text = MessageTemplates.render(template_key, {}, None) or ''
            message_text = _render_message(tpl_text, lead) if tpl_text else ''
        elif message_text:
            # Remplacer les variables {Prenom}, {Ville}, etc. avec les données du lead
            message_text = _render_message(message_text, lead)

        if not message_text:
            return jsonify({"success": False, "error": "Message vide"}), 400

        # Envoyer via Evolution API
        result = evolution_api.send_text(phone, message_text)

        if result.get('success'):
            # Enregistrer dans Redis
            redis_client.add_message(phone, "assistant", message_text)

            now_iso = datetime.now().isoformat()
            # Marquer comme contacté (passage vers encart "Contacté" dans le workflow)
            leads_manager.update_lead(phone, {
                "last_message_at": now_iso,
                "sent_at": now_iso,
                "state": "envoye",
                "etat": "envoye",
            })

            # Retirer de hidden pour que la conversation soit visible
            phone_clean = phone.lstrip('+')
            hidden = _load_hidden()
            if phone_clean in hidden:
                hidden.discard(phone_clean)
                _save_hidden(hidden)

            logger.info(f"📤 Message envoyé: {phone}")

            return jsonify({
                "success": True,
                "message": "Message envoyé",
                "phone": phone
            })
        else:
            # Tout échec d'envoi (absent WhatsApp, timeout, refus, etc.) → non délivré
            err_str = str(result.get('error', ''))
            leads_manager.update_lead(phone, {"etat": "non_whatsapp", "state": "non_whatsapp"})
            logger.warning(f"📵 Échec envoi → non délivré: {phone} — {err_str}")
            return jsonify({"success": False, "error": err_str or "Échec envoi"}), 400

    except Exception as e:
        logger.error(f"Error sending message: {e}")
        # Exception inattendue → aussi marquer non délivré
        try:
            leads_manager.update_lead(phone, {"etat": "non_whatsapp", "state": "non_whatsapp"})
        except Exception:
            pass
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/leads/<phone>/state', methods=['POST'])
def update_state(phone):
    """Change l'état d'un lead"""
    try:
        data = request.json
        new_state = data.get('state', '')
        
        valid_states = ["initial", "message_a_envoyer", "en_cours", "rdv_propose", 
                       "rdv_confirme", "relance", "clos"]
        
        if new_state not in valid_states:
            return jsonify({"success": False, "error": f"État invalide: {new_state}"}), 400
        
        update_lead_state(phone, new_state)
        
        logger.info(f"🔄 État mis à jour: {phone} → {new_state}")
        
        return jsonify({
            "success": True,
            "message": f"État mis à jour: {new_state}",
            "phone": phone,
            "state": new_state
        })
    
    except Exception as e:
        logger.error(f"Error updating state: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/leads/<phone>/toggle-ai', methods=['POST'])
def toggle_ai(phone):
    """Active/désactive l'IA pour une conversation"""
    try:
        new_state = leads_manager.toggle_ai(phone)
        
        if new_state is None:
            return jsonify({"success": False, "error": "Lead non trouvé"}), 404
        
        logger.info(f"🤖 IA toggled: {phone} → {'ON' if new_state else 'OFF'}")
        
        return jsonify({
            "success": True,
            "phone": phone,
            "ai_enabled": new_state,
            "message": "IA " + ("activée" if new_state else "désactivée")
        })
    
    except Exception as e:
        logger.error(f"Error toggling AI: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/stats', methods=['GET'])
def get_stats():
    """Récupère les stats globales"""
    try:
        stats = leads_manager.get_stats()
        
        return jsonify({
            "success": True,
            "stats": stats
        })
    
    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

# ── Compteur journalier anti-ban ──────────────────────────────────────────────
import json as _json_mod
_DAILY_COUNTER_FILE = os.path.join(os.path.dirname(__file__), 'daily_send_counter.json')

def _get_daily_count():
    today = datetime.now().strftime('%Y-%m-%d')
    try:
        with open(_DAILY_COUNTER_FILE) as f:
            data = _json_mod.load(f)
        if data.get('date') == today:
            return data.get('count', 0)
    except Exception:
        pass
    return 0

def _increment_daily_count(n=1):
    today = datetime.now().strftime('%Y-%m-%d')
    count = _get_daily_count() + n
    with open(_DAILY_COUNTER_FILE, 'w') as f:
        _json_mod.dump({'date': today, 'count': count}, f)
    return count

@app.route('/api/campaign/daily-count', methods=['GET'])
def get_daily_count():
    return jsonify({'count': _get_daily_count(), 'limit': 40})

@app.route('/api/campaign/launch', methods=['POST'])
def launch_campaign():
    """Lance une campagne avec protections anti-ban WhatsApp"""
    import random, time as _time
    try:
        data = request.json
        dry_run = data.get('dry_run', False)
        message_tpl = data.get('message', '').strip()
        input_leads = data.get('leads', [])

        if not message_tpl:
            return jsonify({"success": False, "error": "Message vide"}), 400

        # ── Vérification plage horaire (8h-20h) ──
        hour = datetime.now().hour
        if not dry_run and (hour < 8 or hour >= 20):
            return jsonify({
                "success": False,
                "error": f"Envoi autorisé uniquement entre 8h et 20h (heure actuelle : {hour}h)"
            }), 400

        # ── Vérification limite journalière ──
        DAILY_LIMIT = 40
        daily_count = _get_daily_count()
        if not dry_run and daily_count >= DAILY_LIMIT:
            return jsonify({
                "success": False,
                "error": f"Limite journalière atteinte ({DAILY_LIMIT} messages/jour). Reprise demain."
            }), 400

        if not input_leads:
            input_leads = leads_manager.list_leads()

        # Limiter au quota restant
        remaining = DAILY_LIMIT - daily_count
        batch = input_leads[:remaining] if not dry_run else input_leads[:50]

        sent, errors, skipped = 0, 0, 0

        for i, lead in enumerate(batch):
            phone = lead.get('phone') or lead.get('telephone', '')
            if not phone:
                skipped += 1
                continue

            msg = _render_message(message_tpl, lead)

            if dry_run:
                logger.info(f"[DRY-RUN] → {phone}: {msg[:60]}...")
                sent += 1
                continue

            result = evolution_api.send_text(phone, msg)
            if result.get('success'):
                logger.info(f"✅ Envoyé → {phone}")
                leads_manager.update_lead(phone, {
                    'sent_at': datetime.now().isoformat(),
                    'state': 'envoye',
                    'etat': 'envoye'
                })
                hidden = _load_hidden()
                phone_clean = phone.lstrip('+')
                if phone_clean in hidden:
                    hidden.discard(phone_clean)
                    _save_hidden(hidden)
                sent += 1
                _increment_daily_count(1)
            else:
                err_str = str(result.get('error', ''))
                logger.error(f"❌ Erreur → {phone}: {result}")
                # Marquer non délivré (absent WhatsApp ou autre erreur)
                leads_manager.update_lead(phone, {"etat": "non_whatsapp", "state": "non_whatsapp"})
                errors += 1

            # ── Délai humain entre chaque message ──
            if i < len(batch) - 1:
                # Pause plus longue toutes les 10 messages (simulation pause naturelle)
                if (i + 1) % 10 == 0:
                    pause = random.uniform(60, 120)
                    logger.info(f"⏸ Pause longue ({pause:.0f}s) après {i+1} messages")
                else:
                    pause = random.uniform(15, 45)
                _time.sleep(pause)

        logger.info(f"Campagne terminée: {sent} envoyés, {errors} erreurs, {skipped} ignorés | Total jour: {_get_daily_count()}")
        return jsonify({
            "success": True,
            "message": f"{'[DRY-RUN] ' if dry_run else ''}{sent} message(s) envoyé(s), {errors} erreur(s)",
            "sent": sent,
            "errors": errors,
            "skipped": skipped,
            "dry_run": dry_run,
            "daily_total": _get_daily_count()
        })

    except Exception as e:
        logger.error(f"Error launching campaign: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/miizy/api/commerciaux', methods=['GET'])
def miizy_get_commerciaux():
    """Retourne la liste des commerciaux Miizy configurés avec leur numéro WhatsApp."""
    if not session.get('user_email'):
        return jsonify({'error': 'Non authentifié'}), 401
    commerciaux = []
    for comm_id, cfg in CONFIG.get('miizy_commerciaux', {}).items():
        phone = cfg.get('phone', '')
        # Tenter de récupérer le numéro depuis Evolution API
        if not phone:
            try:
                evo = _get_commercial_evo(comm_id)
                if evo:
                    import requests as _req
                    hdrs = {"apikey": evo.api_key}
                    # Essai 1 : connectionState
                    r = _req.get(f"{evo.base_url}/instance/connectionState/{evo.instance_name}", headers=hdrs, timeout=5)
                    if r.status_code == 200:
                        rj = r.json()
                        owner = rj.get('instance', {}).get('owner', '') or rj.get('owner', '')
                        if owner:
                            phone = '+' + owner.split('@')[0] if '@' in owner else owner
                    # Essai 2 : fetchInstances (retourne owner direct)
                    if not phone:
                        r2 = _req.get(f"{evo.base_url}/instance/fetchInstances", headers=hdrs, timeout=5)
                        if r2.status_code == 200:
                            instances = r2.json()
                            if isinstance(instances, list):
                                for inst in instances:
                                    if inst.get('instance', {}).get('instanceName') == evo.instance_name:
                                        owner = inst.get('instance', {}).get('owner', '')
                                        if owner:
                                            phone = '+' + owner.split('@')[0] if '@' in owner else owner
                                        break
            except Exception:
                pass
        commerciaux.append({'id': comm_id, 'name': cfg.get('name', comm_id), 'phone': phone})
    return jsonify({'success': True, 'commerciaux': commerciaux})


@app.route('/miizy/api/campaign/launch-background', methods=['POST'])
def miizy_launch_background_campaign():
    """Lance une campagne Miizy en arrière-plan — non bloquant, indépendant du navigateur."""
    try:
        data = request.json or {}
        message_tpl = data.get('message', '').strip()
        if not message_tpl:
            return jsonify({"success": False, "error": "Message vide"}), 400

        hour = datetime.now().hour
        if hour < 8 or hour >= 20:
            return jsonify({
                "success": False,
                "error": f"Envoi autorisé entre 8h et 20h (heure actuelle : {hour}h)"
            }), 400

        input_leads = data.get('leads', [])
        if not input_leads:
            input_leads = miizy_leads_manager.list_leads()

        valid_leads = [l for l in input_leads if l.get('phone')]
        if not valid_leads:
            return jsonify({"success": False, "error": "Aucun lead avec numéro valide"}), 400

        commercial_id = data.get('commercial_id') or ''

        job_id = f"miizy_{int(datetime.now().timestamp())}"
        progress_key = f"{_MIIZY_CAMPAIGN_PROGRESS_PREFIX}{job_id}"

        job_data = {
            "job_id": job_id,
            "commercial_id": commercial_id,
            "total": len(valid_leads),
            "sent": 0,
            "errors": 0,
            "current_index": 0,
            "status": "running",
            "started_at": datetime.now().isoformat(),
        }
        redis_client.client.setex(progress_key, 86400, json.dumps(job_data))

        t = threading.Thread(
            target=_miizy_campaign_worker,
            args=(job_id, message_tpl, valid_leads, commercial_id),
            daemon=True,
            name=f"miizy_campaign_{job_id}",
        )
        t.start()

        logger.info(f"[Miizy][Campaign] Job {job_id} démarré — {len(valid_leads)} leads")
        return jsonify({"success": True, "job_id": job_id, "total": len(valid_leads)})

    except Exception as e:
        logger.error(f"[Miizy][Campaign] Erreur lancement: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/miizy/api/campaign/progress/<job_id>', methods=['GET'])
def miizy_campaign_progress(job_id):
    """Retourne la progression en temps réel d'une campagne background."""
    try:
        raw = redis_client.client.get(f"{_MIIZY_CAMPAIGN_PROGRESS_PREFIX}{job_id}")
        if not raw:
            return jsonify({"success": False, "error": "Job introuvable ou expiré"}), 404
        return jsonify({"success": True, **json.loads(raw)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/miizy/api/campaign/cancel/<job_id>', methods=['POST'])
def miizy_campaign_cancel(job_id):
    """Annule une campagne background en cours."""
    try:
        key = f"{_MIIZY_CAMPAIGN_PROGRESS_PREFIX}{job_id}"
        raw = redis_client.client.get(key)
        if not raw:
            return jsonify({"success": False, "error": "Job introuvable"}), 404
        jd = json.loads(raw)
        jd["status"] = "cancelled"
        redis_client.client.setex(key, 86400, json.dumps(jd))
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/miizy/api/sequences/run', methods=['POST'])
def miizy_sequences_run_now():
    """Déclenche manuellement un cycle de séquences (admin uniquement)."""
    if not session.get('user_email'):
        return jsonify({'error': 'Non authentifié'}), 401
    if session.get('user_role') != 'admin':
        return jsonify({'error': 'Accès refusé'}), 403
    try:
        threading.Thread(target=_miizy_run_sequences, daemon=True).start()
        return jsonify({"success": True, "message": "Cycle de séquences lancé en arrière-plan"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


MIIZY_TEMPLATE_DEFAULTS = {
    "ouverture": "Bonjour {Prenom},\n\nVous travaillez sur du neuf, ou uniquement de l'ancien ?",
    "relance_24h": "Bonjour {Prenom}, je voulais juste prendre de vos nouvelles — avez-vous eu le temps de regarder mon message précédent ?",
    "relance_72h": "Bonjour {Prenom}, je ne veux pas vous déranger davantage — si jamais vous souhaitez en savoir plus sur Miizy, je reste disponible quand vous voulez. Bonne journée !",
}

# ══════════════════════════════════════════════════════════════════════════════
# MOTEUR DE SÉQUENCES AUTOMATIQUES MIIZY (Phase 1)
# Cron côté serveur : check toutes les 30 min
# envoye +24h → relance_24h | relance_24h +72h → relance_72h | relance_72h +7j → cloture
# ══════════════════════════════════════════════════════════════════════════════

def _miizy_load_templates_for_sequences() -> dict:
    """Charge les templates Miizy (custom ou défauts)."""
    try:
        custom = {}
        if os.path.exists('miizy_templates.json'):
            custom = json.load(open('miizy_templates.json', 'r', encoding='utf-8'))
        result = {}
        for key, default_text in MIIZY_TEMPLATE_DEFAULTS.items():
            result[key] = custom.get(key, default_text)
        return result
    except Exception:
        return dict(MIIZY_TEMPLATE_DEFAULTS)


def _miizy_run_sequences():
    """Exécute les séquences automatiques Miizy — appelé toutes les 30 min."""
    import time as _t
    now = datetime.now()
    templates = _miizy_load_templates_for_sequences()
    tpl_24h = templates.get("relance_24h", MIIZY_TEMPLATE_DEFAULTS["relance_24h"])
    tpl_72h = templates.get("relance_72h", MIIZY_TEMPLATE_DEFAULTS["relance_72h"])

    try:
        all_leads = miizy_leads_manager.list_leads()
    except Exception as e:
        logger.warning(f"[Miizy][Seq] Impossible de charger les leads: {e}")
        return

    sent_count = cloture_count = 0

    for lead in all_leads:
        phone = lead.get("phone", "")
        state = lead.get("state", "")
        if not phone or not state:
            continue

        # Ignorer les leads en pause commerciale, déjà clôturés, non WhatsApp
        if state in ("pause", "cloture", "non_whatsapp", "rdv_confirme", "clos"):
            continue

        try:
            if state == "envoye":
                # J0 + 24h sans réponse → relance_24h
                ref_str = lead.get("sent_at") or lead.get("created_at", "")
                if not ref_str:
                    continue
                ref_dt = datetime.fromisoformat(ref_str)
                if (now - ref_dt).total_seconds() >= 24 * 3600:
                    msg = _render_message(tpl_24h, lead)
                    result = miizy_evolution_api.send_text(phone, msg)
                    if result.get("success"):
                        miizy_leads_manager.update_lead(phone, {
                            "state": "relance_24h",
                            "etat": "relance_24h",
                            "relance_24h_sent_at": now.isoformat(),
                        })
                        logger.info(f"[Miizy][Seq] Relance 24h envoyée → {phone}")
                        sent_count += 1
                        _t.sleep(2)  # petite pause anti-spam

            elif state == "relance_24h":
                # relance_24h + 72h sans réponse → relance_72h
                ref_str = lead.get("relance_24h_sent_at", "")
                if not ref_str:
                    # Fallback sur sent_at si relance_24h_sent_at absent
                    ref_str = lead.get("sent_at") or lead.get("created_at", "")
                    if not ref_str:
                        continue
                ref_dt = datetime.fromisoformat(ref_str)
                if (now - ref_dt).total_seconds() >= 72 * 3600:
                    msg = _render_message(tpl_72h, lead)
                    result = miizy_evolution_api.send_text(phone, msg)
                    if result.get("success"):
                        miizy_leads_manager.update_lead(phone, {
                            "state": "relance_72h",
                            "etat": "relance_72h",
                            "relance_72h_sent_at": now.isoformat(),
                        })
                        logger.info(f"[Miizy][Seq] Relance 72h envoyée → {phone}")
                        sent_count += 1
                        _t.sleep(2)

            elif state == "relance_72h":
                # relance_72h + 7j sans réponse → clôture automatique
                ref_str = lead.get("relance_72h_sent_at", "")
                if not ref_str:
                    ref_str = lead.get("sent_at") or lead.get("created_at", "")
                    if not ref_str:
                        continue
                ref_dt = datetime.fromisoformat(ref_str)
                if (now - ref_dt).total_seconds() >= 7 * 24 * 3600:
                    miizy_leads_manager.update_lead(phone, {
                        "state": "cloture",
                        "etat": "cloture",
                        "cloture_tag": "Séquence terminée — aucune réponse",
                        "cloture_at": now.isoformat(),
                    })
                    logger.info(f"[Miizy][Seq] Clôture auto → {phone}")
                    cloture_count += 1

        except Exception as e:
            logger.warning(f"[Miizy][Seq] Erreur pour {phone}: {e}")

    if sent_count or cloture_count:
        logger.info(f"[Miizy][Seq] Cycle terminé — {sent_count} envoi(s), {cloture_count} clôture(s)")


def _miizy_sequence_engine_start():
    """Démarre le moteur de séquences Miizy en arrière-plan (thread daemon)."""
    import time as _t

    def _loop():
        _t.sleep(60)  # Attendre 60s au démarrage que tout soit initialisé
        while True:
            try:
                _miizy_run_sequences()
            except Exception as e:
                logger.error(f"[Miizy][Seq] Erreur inattendue: {e}")
            _t.sleep(30 * 60)  # Toutes les 30 minutes

    t = threading.Thread(target=_loop, daemon=True, name="miizy_sequence_engine")
    t.start()
    logger.info("[Miizy] Moteur de séquences démarré (interval: 30 min)")


# ══════════════════════════════════════════════════════════════════════════════
# CAMPAGNE BACKGROUND MIIZY (Phase 3)
# File Redis + worker indépendant du navigateur
# ══════════════════════════════════════════════════════════════════════════════

_MIIZY_CAMPAIGN_PROGRESS_PREFIX = "miizy:campaign:progress:"


def _miizy_campaign_worker(job_id: str, message_tpl: str, leads: list, commercial_id: str = ''):
    """Worker campagne Miizy — tourne en arrière-plan, indépendant du navigateur."""
    import random, time as _t
    progress_key = f"{_MIIZY_CAMPAIGN_PROGRESS_PREFIX}{job_id}"
    # Instance Evolution à utiliser : commercial sélectionné ou Adam par défaut
    _evo = _get_commercial_evo(commercial_id or 'adam')

    sent = errors = 0

    for i, lead in enumerate(leads):
        # Lire le statut (annulation possible depuis le dashboard)
        try:
            raw = redis_client.client.get(progress_key)
            if not raw:
                break
            job_data = json.loads(raw)
            if job_data.get("status") == "cancelled":
                logger.info(f"[Miizy][Campaign] Job {job_id} annulé à {i}/{len(leads)}")
                break
        except Exception:
            pass

        # Vérifier plage horaire (8h-20h) — pause si nuit
        hour = datetime.now().hour
        if hour < 8 or hour >= 20:
            logger.info(f"[Miizy][Campaign] Hors plage — job {job_id} suspendu (nuit)")
            try:
                raw = redis_client.client.get(progress_key)
                if raw:
                    jd = json.loads(raw)
                    jd.update({"status": "paused_night", "sent": sent, "errors": errors, "current_index": i})
                    redis_client.client.setex(progress_key, 86400, json.dumps(jd))
            except Exception:
                pass
            break

        phone = lead.get("phone", "")
        if not phone:
            continue

        msg = _render_message(message_tpl, lead)
        result = _evo.send_text(phone, msg)

        if result.get("success"):
            try:
                _upd = {
                    "sent_at": datetime.now().isoformat(),
                    "state": "envoye",
                    "etat": "envoye",
                }
                if commercial_id:
                    _upd["commercial_id"] = commercial_id
                miizy_leads_manager.update_lead(phone, _upd)
            except Exception:
                pass
            sent += 1
        else:
            try:
                miizy_leads_manager.update_lead(phone, {"state": "non_whatsapp", "etat": "non_whatsapp"})
            except Exception:
                pass
            errors += 1

        # Mettre à jour la progression
        try:
            raw = redis_client.client.get(progress_key)
            if raw:
                jd = json.loads(raw)
                jd.update({"sent": sent, "errors": errors, "current_index": i + 1})
                redis_client.client.setex(progress_key, 86400, json.dumps(jd))
        except Exception:
            pass

        # Pause anti-ban : ~13 min entre messages (configurable — 5/heure)
        if i < len(leads) - 1:
            if (i + 1) % 5 == 0:
                pause = random.uniform(75, 90)   # pause plus longue tous les 5
            else:
                pause = random.uniform(10, 20)   # pause courte intra-burst
            _t.sleep(pause)

    # Marquer terminé
    try:
        raw = redis_client.client.get(progress_key)
        if raw:
            jd = json.loads(raw)
            if jd.get("status") not in ("cancelled", "paused_night"):
                jd.update({"status": "done", "sent": sent, "errors": errors})
                redis_client.client.setex(progress_key, 86400, json.dumps(jd))
    except Exception:
        pass

    logger.info(f"[Miizy][Campaign] Job {job_id} terminé — {sent} envoyés, {errors} erreurs")

def _templates_file():
    """Retourne le fichier de templates selon l'agent actif."""
    if '/miizy/' in (request.path or ''):
        return 'miizy_templates.json'
    return 'templates_custom.json'

def _load_custom_templates(filepath):
    try:
        if os.path.exists(filepath):
            return json.load(open(filepath, 'r', encoding='utf-8'))
    except Exception:
        pass
    return {}

def _save_custom_templates(filepath, data):
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


@app.route('/api/templates', methods=['GET'])
@app.route('/miizy/api/templates', methods=['GET'])
def get_templates():
    """Récupère tous les templates de messages (Vianova ou Miizy)."""
    try:
        filepath = _templates_file()
        custom = _load_custom_templates(filepath)
        if '/miizy/' in request.path:
            # Pour Miizy : retourner les templates Miizy (custom ou défauts)
            result = {}
            for key, default_text in MIIZY_TEMPLATE_DEFAULTS.items():
                result[key] = custom.get(key, default_text)
        else:
            # Pour Vianova : retourner les templates MessageTemplates + overrides custom
            base = MessageTemplates.list_templates()
            result = {k: v.copy() for k, v in base.items()}
            for key, text in custom.items():
                if key in result:
                    result[key]['text'] = text
                else:
                    result[key] = {'text': text}
        return jsonify({"success": True, "templates": result})
    except Exception as e:
        logger.error(f"Error getting templates: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/templates/<template_key>', methods=['POST'])
@app.route('/miizy/api/templates/<template_key>', methods=['POST'])
def save_template(template_key):
    """Sauvegarde un template de message."""
    try:
        data = request.json or {}
        content = data.get('content', '').strip()
        if not content:
            return jsonify({"success": False, "error": "Contenu vide"}), 400
        filepath = _templates_file()
        templates = _load_custom_templates(filepath)
        templates[template_key] = content
        _save_custom_templates(filepath, templates)
        logger.info(f"Template '{template_key}' sauvegardé dans {filepath}")
        return jsonify({"success": True})
    except Exception as e:
        logger.error(f"Error saving template: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/templates/<template_key>/preview', methods=['GET'])
def preview_template(template_key):
    """Aperçu d'un template avec variables par défaut"""
    try:
        preview = MessageTemplates.preview(template_key)
        return jsonify({
            "success": True,
            "template_key": template_key,
            "preview": preview
        })
    except Exception as e:
        logger.error(f"Error previewing template: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/templates/<template_key>/render', methods=['POST'])
def render_template(template_key):
    """Rendu d'un template avec variables réelles"""
    try:
        data = request.json
        variables = data.get('variables', {})
        custom_text = data.get('custom_text')
        
        rendered = MessageTemplates.render(template_key, variables, custom_text)
        
        return jsonify({
            "success": True,
            "template_key": template_key,
            "rendered": rendered
        })
    except Exception as e:
        logger.error(f"Error rendering template: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/relance/check', methods=['POST'])
def check_relances():
    """Vérifie et envoie les relances nécessaires"""
    try:
        leads = leads_manager.get_leads_needing_relance(hours=24)
        
        relanced = []
        for lead in leads:
            phone = lead.get('phone', '')
            
            # Envoyer relance
            relance_msg = "Bonjour, avez-vous eu du temps pour réfléchir à votre projet immobilier ?"
            result = evolution_api.send_text(phone, relance_msg)
            
            if result.get('success'):
                update_lead_state(phone, "relance")
                redis_client.add_message(phone, "system", "Relance automatique envoyée")
                relanced.append(phone)
                logger.info(f"⏰ Relance envoyée: {phone}")
        
        return jsonify({
            "success": True,
            "relanced": relanced,
            "count": len(relanced)
        })
    
    except Exception as e:
        logger.error(f"Error checking relances: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ==================== CONVERSATIONS ====================

@app.route('/api/conversations', methods=['GET'])
def get_conversations():
    """Récupère toutes les conversations depuis Evolution API"""
    try:
        import requests as req
        _is_miizy = '/miizy/' in request.path
        if _is_miizy:
            commercial_id = request.args.get('commercial_id') or 'adam'
            _comm_cfg = CONFIG.get('miizy_commerciaux', {}).get(commercial_id, {})
            _evo_obj = _get_commercial_evo(commercial_id)
            _evo = {
                'api_key': _comm_cfg.get('api_key', _miizy_evo_cfg['api_key']),
                'instance_name': _comm_cfg.get('instance_name', _miizy_evo_cfg['instance_name']),
                'base_url': _comm_cfg.get('base_url', _miizy_evo_cfg['base_url']),
            }
        else:
            commercial_id = None
            _evo = CONFIG['evolution_api']
        headers = {
            'apikey': _evo['api_key'],
            'Content-Type': 'application/json'
        }
        instance = _evo['instance_name']
        base = _evo['base_url']

        r = req.post(f'{base}/chat/findChats/{instance}', headers=headers, json={}, timeout=10)
        if r.status_code >= 400:
            logger.error(f"[get_conversations] Evolution API {instance} erreur {r.status_code}: {r.text[:300]}")
            return jsonify({"success": False, "error": r.text}), 500

        raw = r.json()
        logger.info(f"[get_conversations] {instance} → type={type(raw).__name__}, keys={list(raw.keys()) if isinstance(raw, dict) else 'list'}, len={len(raw) if isinstance(raw, (list,dict)) else '?'}")
        # Evolution API peut retourner une liste ou un dict avec clé 'chats'/'data'/'records'
        if isinstance(raw, list):
            chats = raw
        elif isinstance(raw, dict):
            chats = raw.get('chats') or raw.get('data') or raw.get('records') or []
        else:
            chats = []

        conversations = []
        for chat in chats:
            if not isinstance(chat, dict):
                continue
            jid = chat.get('remoteJid', '')
            # Résoudre les JIDs @lid vers le vrai numéro via lastMessage.key.remoteJidAlt
            last_msg = chat.get('lastMessage') or {}
            last_key = last_msg.get('key') or {}
            alt_jid = last_key.get('remoteJidAlt', '')
            if '@lid' in jid and alt_jid and '@s.whatsapp.net' in alt_jid:
                jid = alt_jid
            phone = jid.split('@')[0] if '@' in jid else jid
            # Normaliser : enlever le +
            phone = phone.lstrip('+')
            last_text = ''
            if last_msg:
                msg_body = last_msg.get('message') or {}
                last_text = msg_body.get('conversation') or (msg_body.get('extendedTextMessage') or {}).get('text', '') or ''

            # Lire le stage depuis la mémoire de l'agent
            conv_stage = ''
            try:
                if _is_miizy:
                    # Miizy : stage dans Redis session
                    raw = redis_client.client.get(f"miizy:session:{phone}")
                    if raw:
                        import json as _j
                        conv_stage = _j.loads(raw).get('step', '')
                else:
                    from pathlib import Path as _P
                    conv_file = _P('/data/.openclaw/workspace/vianova-agent/conversations') / f'{phone}.json'
                    if conv_file.exists():
                        import json as _j
                        conv_data = _j.loads(conv_file.read_text())
                        conv_stage = conv_data.get('stage', '')
            except Exception:
                pass

            conversations.append({
                'id': chat.get('id'),
                'phone': phone,
                'jid': jid,
                'name': chat.get('pushName') or phone,
                'profilePicUrl': chat.get('profilePicUrl'),
                'updatedAt': chat.get('updatedAt'),
                'unreadCount': chat.get('unreadCount') or 0,
                'lastMessage': last_text,
                'lastMessageFromMe': last_key.get('fromMe', False),
                'lastMessageAt': last_msg.get('messageTimestamp') if last_msg else None,
                'stage': conv_stage,
            })

        # Construire la map d'état des leads pour l'enrichissement
        if _is_miizy:
            all_leads = miizy_leads_manager.list_leads()
        else:
            all_leads = leads_manager.list_leads()
        if not all_leads:
            all_leads = []

        lead_phones = set()
        lead_states = {}
        lead_ai_enabled = {}
        lead_humain_depuis = {}
        lead_commercial = {}  # phone → commercial_id
        for l in all_leads:
            if not isinstance(l, dict):
                continue
            for key in ('phone', 'telephone'):
                p = (l.get(key) or '').lstrip('+')
                if p:
                    lead_phones.add(p)
                    lead_states[p] = l.get('state', '')
                    lead_ai_enabled[p] = l.get('ai_enabled', True)
                    lead_commercial[p] = l.get('commercial_id', 'adam') or 'adam'
                    if l.get('agent_humain_depuis'):
                        lead_humain_depuis[p] = l['agent_humain_depuis']

        hidden = _load_hidden()
        if _is_miizy:
            # Filtrer par commercial_id : seuls les leads assignés à ce commercial
            filtered_lead_phones = {p for p, cid in lead_commercial.items() if cid == commercial_id}
            conversations = [c for c in conversations if c['phone'] in filtered_lead_phones and c['phone'] not in hidden]
        else:
            # Vianova : filtrer uniquement les leads connus
            if lead_phones:
                conversations = [c for c in conversations if c['phone'] in lead_phones and c['phone'] not in hidden]
            else:
                conversations = [c for c in conversations if c['phone'] not in hidden]

        # Enrichir avec l'état du lead
        for c in conversations:
            p = c['phone']
            c['agent_paused'] = (lead_states.get(p, '') == 'pause') or (not lead_ai_enabled.get(p, True))
            c['agent_humain_depuis'] = lead_humain_depuis.get(p)
            c['commercial_id'] = lead_commercial.get(p, 'adam') if _is_miizy else None
            # Miizy : remplacer le step interne par le vrai état du lead
            if _is_miizy and lead_states.get(p):
                c['stage'] = lead_states[p]
        conversations.sort(key=lambda x: x.get('lastMessageAt') or 0, reverse=True)
        return jsonify({"success": True, "conversations": conversations})

    except Exception as e:
        import traceback
        logger.error(f"Error getting conversations: {e}\n{traceback.format_exc()}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/conversations/<path:jid>/messages', methods=['GET'])
def get_conversation_messages(jid):
    """Récupère les messages d'une conversation (Evolution API + mémoire locale)"""
    try:
        import requests as req
        from pathlib import Path
        from datetime import datetime as dt

        _is_miizy = '/miizy/' in request.path
        _evo = _miizy_evo_cfg if _is_miizy else CONFIG['evolution_api']

        # Normaliser le phone pour chercher le fichier local
        phone_clean = jid.replace('@s.whatsapp.net', '').replace('@c.us', '').replace('+', '').strip()

        # --- 1. Récupérer les messages Evolution API (sortants principalement) ---
        headers = {
            'apikey': _evo['api_key'],
            'Content-Type': 'application/json'
        }
        instance = _evo['instance_name']
        base = _evo['base_url']
        if '@' not in jid:
            jid = jid + '@s.whatsapp.net'

        evo_messages = []
        try:
            # Phase 4 : essayer plusieurs formats JID (@s.whatsapp.net et @lid)
            _jid_candidates = [jid]
            if '@lid' in jid:
                # Fallback vers @s.whatsapp.net si on a un @lid
                _jid_candidates.append(f"{phone_clean}@s.whatsapp.net")
            elif '@s.whatsapp.net' not in jid and '@c.us' not in jid:
                _jid_candidates = [f"{phone_clean}@s.whatsapp.net", f"{phone_clean}@c.us"]

            def _parse_evo_records(records):
                parsed = []
                for msg in records:
                    msg_body = msg.get('message', {}) or {}
                    text = (msg_body.get('conversation')
                            or msg_body.get('extendedTextMessage', {}).get('text', '')
                            or msg_body.get('imageMessage', {}).get('caption', '')
                            or msg_body.get('videoMessage', {}).get('caption', '')
                            or msg_body.get('documentMessage', {}).get('caption', '')
                            or msg_body.get('buttonsResponseMessage', {}).get('selectedDisplayText', '')
                            or msg_body.get('listResponseMessage', {}).get('title', '')
                            or '')
                    msg_type = msg.get('messageType', 'conversation')
                    if not text and msg_type in ('imageMessage', 'videoMessage', 'audioMessage', 'documentMessage', 'stickerMessage'):
                        text = f'[{msg_type.replace("Message", "")}]'
                    from_me = msg.get('key', {}).get('fromMe', False)
                    parsed.append({
                        'id': msg.get('key', {}).get('id', msg.get('id')),
                        'fromMe': from_me,
                        'text': text,
                        'timestamp': msg.get('messageTimestamp'),
                        'status': msg.get('MessageUpdate', [{}])[-1].get('status', '') if msg.get('MessageUpdate') else '',
                        'type': msg_type,
                    })
                return parsed

            for _jid_try in _jid_candidates:
                try:
                    payload = {'where': {'key': {'remoteJid': _jid_try}}}
                    r = req.post(f'{base}/chat/findMessages/{instance}', headers=headers, json=payload, timeout=10)
                    if r.status_code < 400:
                        data = r.json()
                        records = data.get('messages', {}).get('records', data if isinstance(data, list) else [])
                        if records:
                            evo_messages = _parse_evo_records(records)
                            break  # Arrêter dès qu'on a des résultats
                except Exception as _e:
                    logger.warning(f"findMessages error for {_jid_try}: {_e}")
                    continue
        except Exception as e:
            logger.warning(f"Evolution API messages error: {e}")

        # --- 2. Récupérer les messages de la mémoire locale (entrée + sortie) ---
        local_messages = []
        if _is_miizy:
            # Miizy : historique stocké dans Redis miizy:session:{phone}
            try:
                raw = redis_client.client.get(f"miizy:session:{phone_clean}")
                if raw:
                    session_data = json.loads(raw)
                    for idx, m in enumerate(session_data.get('history', [])):
                        role = m.get('role', '')
                        local_messages.append({
                            'id': f"miizy_{phone_clean}_{idx}",
                            'fromMe': role == 'assistant',
                            'text': m.get('content', ''),
                            'timestamp': 0,
                            'status': '',
                            'type': 'conversation',
                            '_local': True,
                        })
            except Exception as e:
                logger.warning(f"Miizy Redis session read error: {e}")
            # Charger aussi les messages manuels (commercial + prospect quand bot pausé)
            try:
                manual_raw = redis_client.client.get(f"miizy:manual:{phone_clean}")
                if manual_raw:
                    for m in json.loads(manual_raw):
                        local_messages.append({
                            'id': f"miizy_manual_{phone_clean}_{m.get('timestamp', 0)}",
                            'fromMe': m.get('fromMe', False),
                            'text': m.get('text', ''),
                            'timestamp': m.get('timestamp', 0),
                            'status': '',
                            'type': 'conversation',
                            '_local': True,
                        })
            except Exception as e:
                logger.warning(f"Miizy manual messages read error: {e}")
        else:
            conv_dir = Path(__file__).parent / 'conversations'
            # Chercher le fichier avec ou sans le +
            for candidate in [phone_clean, '+' + phone_clean, '33' + phone_clean[-9:] if len(phone_clean) > 9 else '']:
                conv_file = conv_dir / f'{candidate}.json'
                if conv_file.exists():
                    try:
                        with open(conv_file) as f:
                            conv_data = json.load(f)
                        for m in conv_data.get('messages', []):
                            ts_str = m.get('timestamp', '')
                            try:
                                ts = int(dt.fromisoformat(ts_str).timestamp()) if ts_str else 0
                            except Exception:
                                ts = 0
                            local_messages.append({
                                'id': m.get('message_id', f"local_{ts}_{m.get('role')}"),
                                'fromMe': m.get('role') in ('assistant', 'daniel'),
                                'fromDaniel': m.get('role') == 'daniel',
                                'text': m.get('content', ''),
                                'timestamp': ts,
                                'status': '',
                                'type': 'conversation',
                                '_local': True,
                            })
                    except Exception as e:
                        logger.warning(f"Local conv read error: {e}")
                    break

        # --- 3. Fusionner : Evolution API pour les sortants, local pour les entrants ---
        # Les messages Evolution API sortants (fromMe=True) sont la référence (timestamps exacts)
        # On ajoute les messages entrants (fromMe=False) depuis la mémoire locale
        evo_outgoing_texts = {m['text'].strip() for m in evo_messages if m['fromMe'] and m['text']}
        evo_incoming_texts = {m['text'].strip() for m in evo_messages if not m['fromMe'] and m['text']}

        combined = list(evo_messages)
        for lm in local_messages:
            text = (lm['text'] or '').strip()
            if not lm['fromMe']:
                # Message entrant (user) : ajouter si pas déjà dans Evolution
                if text and text not in evo_incoming_texts:
                    combined.append(lm)
                    evo_incoming_texts.add(text)
            else:
                # Message sortant : pour Miizy (historique Redis) ou Daniel (local json)
                is_agent_msg = _is_miizy or lm.get('fromDaniel')
                if is_agent_msg and text and text not in evo_outgoing_texts:
                    combined.append(lm)
                    evo_outgoing_texts.add(text)

        combined.sort(key=lambda x: x.get('timestamp') or float('inf'))
        # Nettoyer le champ _local
        for m in combined:
            m.pop('_local', None)

        return jsonify({"success": True, "messages": combined})

    except Exception as e:
        logger.error(f"Error getting messages: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/conversations/<path:jid>/send', methods=['POST'])
def send_conversation_message(jid):
    """Envoie un message dans une conversation"""
    try:
        data = request.json
        text = data.get('text', '').strip()
        if not text:
            return jsonify({"success": False, "error": "Message vide"}), 400

        if '@' not in jid:
            jid = jid + '@s.whatsapp.net'
        phone = jid.split('@')[0]

        result = evolution_api.send_text(phone, text)
        return jsonify(result)

    except Exception as e:
        logger.error(f"Error sending message: {e}")
        return jsonify({"success": False, "error": str(e)}), 500



# Liste des conversations masquées (supprimées localement)
import json as _json
from pathlib import Path as _Path
_HIDDEN_FILE = _Path('/data/.openclaw/workspace/vianova-agent/hidden_conversations.json')

def _load_hidden():
    if _HIDDEN_FILE.exists():
        return set(_json.loads(_HIDDEN_FILE.read_text()))
    return set()

def _save_hidden(phones: set):
    _HIDDEN_FILE.write_text(_json.dumps(list(phones)))


@app.route('/api/conversations/<path:phone>/resume', methods=['POST'])
def resume_agent(phone):
    """
    Réactive le bot pour une conversation — UNIQUEMENT via action manuelle depuis le dashboard.
    Aucun timer, aucune réactivation automatique. Le bot reprend depuis session["etape"]
    (ConversationMemory) telle qu'elle était au moment de la prise en main.
    """
    try:
        phone_clean = phone.replace("@s.whatsapp.net", "").replace("@c.us", "").lstrip('+')
        lead = leads_manager.get_lead(phone_clean)
        if not lead:
            return jsonify({"success": False, "error": "lead not found"}), 404

        # Priorité 1 : stage ConversationMemory (jamais modifié pendant la pause)
        try:
            from conversation_memory import ConversationMemory as _CM
            _cm = _CM(phone_clean)
            conv_stage = _cm.get_stage()
        except Exception:
            conv_stage = None

        # Priorité 2 : prev_state sauvegardé au moment de la prise en main
        prev_state = lead.get("prev_state") or ""
        if prev_state == "pause":
            prev_state = ""

        # Résolution finale : conv_stage > prev_state > "initial"
        new_state = conv_stage or prev_state or "initial"

        resume_at = datetime.now().isoformat()
        leads_manager.update_lead(phone_clean, {
            "state": new_state,
            "etat": new_state,
            "prev_state": None,            # nettoyage
            "agent_humain_depuis": None    # suppression timestamp prise en main
        })

        logger.info(f"[Bot 🤖] Bot réactivé manuellement par Daniel à {resume_at} "
                    f"pour {phone_clean} — reprise stage={new_state!r}")

        return jsonify({"success": True, "state": new_state, "resumed_at": resume_at})

    except Exception as e:
        logger.error(f"[resume_agent] erreur: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/conversations/<path:phone>/pause', methods=['POST'])
def pause_agent(phone):
    """Met le bot en pause manuelle (Daniel prend la main via le dashboard)."""
    try:
        phone_clean = phone.replace("@s.whatsapp.net", "").replace("@c.us", "").lstrip('+')
        lead = leads_manager.get_lead(phone_clean)
        if lead:
            prev = lead.get("state", "initial")
            if prev != "pause":
                takeover_at = datetime.now().isoformat()
                leads_manager.update_lead(phone_clean, {
                    "state": "pause",
                    "etat": "pause",
                    "prev_state": prev,
                    "agent_humain_depuis": takeover_at
                })
                logger.info(f"[Daniel 👤] Prise en main manuelle (dashboard) pour {phone_clean} "
                            f"(état sauvegardé: {prev!r}) à {takeover_at}")
            return jsonify({"success": True, "state": "pause"})
        return jsonify({"success": False, "error": "lead not found"}), 404
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/conversations/<path:phone>/delete', methods=['DELETE'])
def delete_conversation(phone):
    """Supprime une conversation : mémoire JSON + Redis + masquage local"""
    from pathlib import Path
    deleted = []
    errors = []

    phone_clean = phone.lstrip('+').replace(' ', '').split('/')[0]

    # 1. Masquer dans la liste locale (persiste au rechargement)
    hidden = _load_hidden()
    hidden.add(phone_clean)
    _save_hidden(hidden)
    deleted.append(f"hidden:{phone_clean}")

    # 2. Supprimer la mémoire JSON de l'agent
    conv_dir = Path('/data/.openclaw/workspace/vianova-agent/conversations')
    for variant in [phone_clean, '+' + phone_clean]:
        f = conv_dir / f"{variant}.json"
        if f.exists():
            f.unlink()
            deleted.append(f"memory:{variant}")

    # 3. Supprimer toutes les clés Redis de conversation (PAS le lead)
    try:
        redis_client.client.delete(f"conv:{phone_clean}")
        redis_client.client.delete(f"miizy:session:{phone_clean}")
        deleted.append(f"redis:conv:{phone_clean}")
    except Exception as e:
        errors.append(f"redis: {e}")

    # 4. Tenter suppression Evolution API (best-effort)
    try:
        import requests as req
        headers = {'apikey': CONFIG['evolution_api']['api_key'], 'Content-Type': 'application/json'}
        instance = CONFIG['evolution_api']['instance_name']
        base = CONFIG['evolution_api']['base_url']
        for suffix in ['@s.whatsapp.net', '@c.us']:
            jid = phone_clean + suffix
            r = req.delete(f"{base}/chat/delete/{instance}", headers=headers, json={"id": jid}, timeout=5)
            if r.status_code < 400:
                deleted.append(f"evolution:{jid}")
                break
    except Exception as e:
        errors.append(f"evolution: {e}")

    # 5. Protéger le lead : relire depuis JSON (source fiable) et re-sauver dans Redis
    #    Garantit que ville/typo et tous les champs ne sont jamais perdus après suppression de conv
    try:
        lead = leads_manager.get_lead(phone_clean)
        if lead:
            # Forcer l'écriture dans Redis ET JSON pour s'assurer de la cohérence
            key = leads_manager._make_lead_key(phone_clean)
            leads_manager.redis.client.set(key, __import__('json').dumps(lead))
            leads_manager._update_lead_in_json(phone_clean, lead)
            logger.info(f"[delete_conversation] Lead protégé: {phone_clean} ville={lead.get('ville')!r} typo={lead.get('typologie')!r}")
    except Exception as _e:
        logger.warning(f"[delete_conversation] lead protect erreur: {_e}")

    logger.info(f"Conversation supprimee {phone_clean}: {deleted}")
    return jsonify({"success": True, "deleted": deleted, "errors": errors, "phone": phone_clean})


@app.route('/api/conversations/hidden/restore/<phone>', methods=['POST'])
def restore_conversation(phone):
    """Restaure une conversation masquée"""
    hidden = _load_hidden()
    hidden.discard(phone.lstrip('+'))
    _save_hidden(hidden)
    return jsonify({"success": True})

# ==================== MESSAGE BUFFER (agrégation multi-messages) ====================
_msg_buffer = {}
_msg_buffer_lock = threading.Lock()
BUFFER_DELAY = 5        # secondes d'attente Vianova
MIIZY_BUFFER_DELAY = 30  # secondes d'attente Miizy (messages multi-parties)



def _calc_typing_delay(text: str, min_s: float = 3.0, max_s: float = 15.0) -> int:
    """Calcule le délai de frappe proportionnel à la longueur du message (en secondes entières)."""
    return max(int(min_s), min(int(max_s), int(len(text) * 0.065)))


def _wait_read_then_type(phone: str, response_text: str) -> int:
    """
    Simule la lecture du message (1.5s) puis retourne le délai de frappe
    à passer à send_text(delay=N) pour afficher l'indicateur 'en train d'écrire'.
    Evolution API gère nativement le composing + envoi différé via le paramètre delay.
    """
    import time as _t
    _t.sleep(7.0)  # pause lecture
    delay_s = _calc_typing_delay(response_text)
    logger.info(f"[timing] {phone} → lecture 1.5s + frappe {delay_s}s ({len(response_text)} chars)")
    return delay_s


def _split_human(text, max_parts=3):
    """Découpe un long message en parties courtes naturelles pour simulation humaine."""
    if not text:
        return []
    text = text.strip()
    if len(text) < 90:
        return [text]
    # Split on sentence boundaries
    parts = re.split(r'(?<=[.!?])\s+', text)
    if len(parts) == 1:
        # No sentence boundary — try splitting near middle
        mid = len(text) // 2
        space = text.find(' ', mid)
        if space > 0 and space < len(text) - 10:
            return [text[:space].strip(), text[space:].strip()]
        return [text]
    # Group into max_parts chunks
    if len(parts) <= max_parts:
        return parts
    # Merge excess sentences into last group
    result = list(parts[:max_parts - 1])
    result.append(' '.join(parts[max_parts - 1:]))
    return [p for p in result if p.strip()]


def _process_buffered(phone):
    """Traite les messages accumulés dans le buffer pour un numéro"""
    with _msg_buffer_lock:
        buf = _msg_buffer.pop(phone, None)
    if not buf:
        return

    texts = buf["texts"]
    ids = buf["ids"]
    aggregated_text = "\n".join(texts)
    primary_id = ids[0] if ids else ""

    logger.info(f"Buffer flush {phone}: {len(texts)} msg(s) -> '{aggregated_text[:80]}'")

    try:
        from agent_ia_minimal import VianovaAgent
        agent_instance = VianovaAgent(phone)

        if primary_id and agent_instance.memory.is_duplicate(primary_id):
            return

        # === SOURCE DE VÉRITÉ : Redis/mémoire conversationnelle ===
        # La fiche lead sert UNIQUEMENT à initialiser la session au premier contact.
        # Dès que la mémoire a des données, elle est la seule source de vérité.
        mem_info = agent_instance.memory.data.get("lead_info", {})
        mem_ville  = mem_info.get("ville", "") or ""
        mem_typo   = mem_info.get("typo", "") or mem_info.get("typologie", "") or ""
        mem_prenom = mem_info.get("prenom", "") or ""
        has_prior_messages = len(agent_instance.memory.data.get("messages", [])) > 0

        if not has_prior_messages or not (mem_ville and mem_typo and mem_prenom):
            # Première prise de contact : initialiser depuis la fiche lead (une seule fois)
            try:
                lead = leads_manager.get_lead(phone)
                if lead:
                    if not mem_prenom:
                        lead_prenom = lead.get("prenom", "") or ""
                        if lead_prenom:
                            agent_instance.memory.update_lead_info(prenom=lead_prenom)
                            mem_prenom = lead_prenom
                    if not mem_ville:
                        lead_ville = lead.get("ville", "") or ""
                        if lead_ville:
                            agent_instance.memory.update_lead_info(ville=lead_ville)
                            mem_ville = lead_ville
                    if not mem_typo:
                        lead_typo = lead.get("typologie", "") or lead.get("type", "") or ""
                        if lead_typo:
                            agent_instance.memory.update_lead_info(typo=lead_typo)
                            mem_typo = lead_typo
            except Exception as e:
                logger.warning(f"Init lead {phone}: {e}")
        # else: mémoire complète → Redis est la source de vérité, on n'interroge pas le lead

        agent_instance.ctx = agent_instance.memory.data.get("lead_info", {})
        agent_instance.ville  = mem_ville
        agent_instance.typo   = mem_typo
        agent_instance.prenom = mem_prenom

        reply1, reply2 = agent_instance.process_message(aggregated_text, primary_id)
        logger.info(f"Agent reponse: '{str(reply1)[:60]}'")

        # Sync état agent → leads.json (clos, rdv_confirme, etc.)
        try:
            agent_stage = agent_instance.memory.get_stage()
            if agent_stage in ('clos', 'rdv_confirme', 'rdv_propose'):
                leads_manager.update_lead(phone, {'state': agent_stage, 'etat': agent_stage})
                logger.info(f"[sync_state] {phone} → {agent_stage}")
        except Exception as _se:
            logger.debug(f"[sync_state] erreur: {_se}")

        # Fallback silencieux : l'agent ne comprend pas → pause immédiate, Daniel prend la main
        if reply1 == "__PAUSE__":
            try:
                lead = leads_manager.get_lead(phone)
                if lead and lead.get("state") != "pause":
                    prev = lead.get("state", "initial")
                    takeover_at = datetime.now().isoformat()
                    leads_manager.update_lead(phone, {
                        "state": "pause",
                        "etat": "pause",
                        "prev_state": prev,
                        "agent_humain_depuis": takeover_at
                    })
                    logger.warning(f"[fallback→pause] {phone} mis en pause auto (stage={prev!r}) — Daniel doit intervenir")
            except Exception as _e:
                logger.error(f"[fallback→pause] erreur: {_e}")
            return  # Aucun message envoyé au prospect

        if reply1:
            import time as _time
            # Anti-doublon webhook : ne pas envoyer si identique au dernier envoi récent (< 10s)
            import threading as _th
            _send_cache = getattr(app, '_send_cache', {})
            app._send_cache = _send_cache
            cache_key = f"{phone}:{(reply1 + reply2).strip()}"
            now_ts = _time.time()
            if cache_key in _send_cache and now_ts - _send_cache[cache_key] < 10:
                logger.warning(f"[send_dedup] message identique bloqué < 10s pour {phone}")
            else:
                _send_cache[cache_key] = now_ts
                # Simulation humaine : découpe les messages en parties courtes
                import re as _re
                all_parts = []
                for _msg in [reply1, reply2]:
                    if _msg:
                        all_parts.extend(_split_human(_msg))
                # Timing humain : lecture (1.5s) → Evolution API affiche composing → envoi
                for _i, _part in enumerate(all_parts):
                    if _i == 0:
                        # Premier message : pause lecture puis delay composing via Evolution API
                        _delay = _wait_read_then_type(phone, _part)
                    else:
                        # Messages suivants : pause inter-message courte
                        _pause = min(2 + len(all_parts[_i - 1]) // 60, 5)
                        _time.sleep(_pause)
                        _delay = _calc_typing_delay(_part, min_s=2.0, max_s=6.0)
                    evolution_api.send_text(phone, _part, delay=_delay)

    except Exception as e:
        logger.error(f"Erreur traitement buffer {phone}: {e}")
        import traceback; traceback.print_exc()


# ==================== WEBHOOK WHATSAPP ====================

@app.route('/webhook/whatsapp', methods=['POST'])
def webhook_whatsapp():
    """Recoit les messages WhatsApp - buffering 15s avant traitement"""
    try:
        data = request.get_json(silent=True) or {}
        event = data.get("event", "")

        if "messages.upsert" not in event:
            return jsonify({"status": "ignored"}), 200

        msg_data = data.get("data", {})
        key = msg_data.get("key", {})

        if key.get("fromMe"):
            # Message envoyé manuellement par Daniel → pause agent + sauvegarde message
            raw_jid = key.get("remoteJid", "")
            alt_jid = key.get("remoteJidAlt", "")
            jid = alt_jid if alt_jid and "@s.whatsapp.net" in alt_jid else raw_jid
            phone_fm = _normalize_phone_number(jid.split("@")[0])
            # Extraire le texte du message de Daniel
            msg_body_fm = msg_data.get("message", {}) or {}
            daniel_text = (msg_body_fm.get("conversation")
                           or msg_body_fm.get("extendedTextMessage", {}).get("text", "")
                           or "").strip()
            if phone_fm:
                try:
                    # Sauvegarder le message de Daniel dans le fichier local
                    if daniel_text:
                        conv_dir = Path(__file__).parent / 'conversations'
                        conv_dir.mkdir(exist_ok=True)
                        conv_file = conv_dir / f'{phone_fm}.json'
                        conv_data = {}
                        if conv_file.exists():
                            try:
                                with open(conv_file) as _f:
                                    conv_data = json.load(_f)
                            except Exception:
                                conv_data = {}
                        msgs = conv_data.get('messages', [])
                        msgs.append({
                            'role': 'daniel',
                            'content': daniel_text,
                            'timestamp': datetime.now().isoformat(),
                            'message_id': key.get('id', ''),
                        })
                        conv_data['messages'] = msgs
                        with open(conv_file, 'w') as _f:
                            json.dump(conv_data, _f, ensure_ascii=False, indent=2)
                        logger.info(f"[Daniel 👤] Message sauvegardé pour {phone_fm}: {daniel_text[:50]!r}")
                    lead = leads_manager.get_lead(phone_fm)
                    if lead and lead.get("state") != "pause":
                        # Sauvegarder l'état actuel AVANT la pause (pour reprise exacte)
                        prev = lead.get("state", "initial")
                        takeover_at = datetime.now().isoformat()
                        leads_manager.update_lead(phone_fm, {
                            "state": "pause",
                            "etat": "pause",
                            "prev_state": prev,                  # état avant prise en main
                            "agent_humain_depuis": takeover_at   # timestamp prise en main Daniel
                        })
                        logger.info(f"[Daniel 👤] Prise en main manuelle pour {phone_fm} "
                                    f"(état sauvegardé: {prev!r}) à {takeover_at}")
                except Exception as _e:
                    logger.warning(f"[human_takeover] erreur pause {phone_fm}: {_e}")
            return jsonify({"status": "from_me_pause"}), 200

        raw_jid = key.get("remoteJid", "")
        alt_jid = key.get("remoteJidAlt", "")
        jid = alt_jid if alt_jid and "@s.whatsapp.net" in alt_jid else raw_jid
        phone = _normalize_phone_number(jid.split("@")[0])

        if not phone:
            return jsonify({"status": "ignored", "reason": "no_phone"}), 200

        message_body = msg_data.get("message", {})
        text = (message_body.get("conversation")
                or message_body.get("extendedTextMessage", {}).get("text")
                or "").strip()

        if not text:
            return jsonify({"status": "ignored", "reason": "no_text"}), 200

        msg_id = key.get("id", "")
        logger.info(f"WEBHOOK message de {phone}: '{text[:80]}'")

        # Marquer le message comme lu (✓✓ bleus) en arrière-plan
        def _mark_read(jid, mid):
            try:
                import requests as _req
                _headers = {'apikey': CONFIG['evolution_api']['api_key'], 'Content-Type': 'application/json'}
                _base = CONFIG['evolution_api']['base_url']
                _inst = CONFIG['evolution_api']['instance_name']
                _req.post(
                    f"{_base}/chat/markMessageAsRead/{_inst}",
                    headers=_headers,
                    json={"readMessages": [{"remoteJid": jid, "fromMe": False, "id": mid}]},
                    timeout=8
                )
            except Exception as _e:
                logger.debug(f"mark_read erreur: {_e}")
        _jid = jid if '@' in jid else f"{phone}@s.whatsapp.net"
        threading.Thread(target=_mark_read, args=(_jid, msg_id), daemon=True).start()

        # Human takeover : si l'agent est en pause, ignorer le message entrant
        try:
            lead = leads_manager.get_lead(phone)
            if lead and lead.get("state") == "pause":
                logger.info(f"[human_takeover] agent en pause pour {phone} — message ignoré")
                return jsonify({"status": "paused"}), 200
        except Exception as _e:
            logger.warning(f"[human_takeover] check pause erreur: {_e}")

        # Mettre à jour last_message_at dès réception (pour classement encart "repondu")
        try:
            leads_manager.update_lead(phone, {"last_message_at": datetime.now().isoformat()})
        except Exception as _e:
            logger.warning(f"update last_message_at erreur: {_e}")

        # Buffer: accumuler, reset timer a chaque nouveau message
        with _msg_buffer_lock:
            if phone in _msg_buffer:
                _msg_buffer[phone]["timer"].cancel()
                _msg_buffer[phone]["texts"].append(text)
                _msg_buffer[phone]["ids"].append(msg_id)
                logger.info(f"Buffer reset {phone} ({len(_msg_buffer[phone]['texts'])} msgs)")
            else:
                _msg_buffer[phone] = {"texts": [text], "ids": [msg_id], "timer": None}
                logger.info(f"Buffer start {phone}")

            timer = threading.Timer(BUFFER_DELAY, _process_buffered, args=[phone])
            timer.daemon = True
            _msg_buffer[phone]["timer"] = timer
            timer.start()

        return jsonify({"status": "buffered", "delay": BUFFER_DELAY}), 200

    except Exception as e:
        logger.error(f"Erreur webhook: {e}")
        import traceback; traceback.print_exc()
        return jsonify({"status": "error", "error": str(e)}), 500


def _normalize_phone_number(raw: str) -> str:
    """Normalise un numéro : enlève +, espaces, garde les chiffres avec indicatif"""
    p = raw.strip().replace("+", "").replace(" ", "").replace("-", "")
    if p.startswith("0") and len(p) == 10:
        p = "33" + p[1:]
    return p if p.isdigit() else ""


def _render_message(template: str, lead: dict) -> str:
    """Remplace les variables {Prenom}, {Ville}, etc. dans un message — insensible à la casse"""
    import re
    from datetime import datetime

    # Mapping : alias (tous en minuscule) → clé dans lead
    aliases = {
        'prenom': 'prenom',
        'nom': 'nom',
        'ville': 'ville',
        'budget': 'budget',
        'typologie': 'typologie',
        'type': 'typologie',
        'dernier contact': 'date_dernier_contact',
        'date dernier contact': 'date_dernier_contact',
        'dernier_contact': 'date_dernier_contact',
        'date': 'date_envoi',
        'date envoi': 'date_envoi',
        'phone': 'phone',
        'telephone': 'telephone',
        'source': 'source',
    }

    def replace_var(match):
        raw = match.group(1)          # texte entre { }
        key = raw.lower().strip()
        lead_key = aliases.get(key, key)
        value = lead.get(lead_key, lead.get(key, ''))
        if not value:
            return match.group(0)     # laisser tel quel si vide
        # Formater les dates au format "12 février 2026"
        if 'date' in lead_key and value:
            _MOIS_LONG = ['janvier','février','mars','avril','mai','juin',
                          'juillet','août','septembre','octobre','novembre','décembre']
            # Essai ISO (stocké par le backend)
            parsed = None
            try:
                parsed = datetime.fromisoformat(str(value))
            except Exception:
                pass
            # Essai texte FR : "12 février 2026"
            if parsed is None:
                import unicodedata as _ud
                _MOIS_NORM = ['janvier','fevrier','mars','avril','mai','juin',
                              'juillet','aout','septembre','octobre','novembre','decembre']
                sn = ''.join(c for c in str(value).lower()
                             if _ud.category(c) != 'Mn' or not _ud.combining(c))
                sn = _ud.normalize('NFD', str(value).lower())
                sn = ''.join(c for c in sn if _ud.category(c) != 'Mn')
                for i, m in enumerate(_MOIS_NORM):
                    if m in sn:
                        parts = str(value).strip().split()
                        try:
                            parsed = datetime(int(parts[2]), i+1, int(parts[0]))
                        except Exception:
                            pass
                        break
            if parsed:
                value = f"{parsed.day} {_MOIS_LONG[parsed.month-1]} {parsed.year}"
        return str(value)

    return re.sub(r'\{([^}]+)\}', replace_var, template)

# ==================== RDV AGENDA ====================


@app.route('/api/costs', methods=['GET'])
def get_costs():
    """Retourne les statistiques de coût LLM (Claude Haiku fallback)."""
    import json as _j, os as _os
    cost_file = _os.path.join(_os.path.dirname(__file__), "llm_costs.json")
    try:
        if _os.path.exists(cost_file):
            with open(cost_file, "r") as f:
                data = _j.load(f)
        else:
            data = {"total_calls": 0, "total_input_tokens": 0, "total_output_tokens": 0, "total_cost_usd": 0.0, "calls": []}
        # Regrouper par jour
        from collections import defaultdict
        from datetime import datetime as _dt
        by_day = defaultdict(lambda: {"calls": 0, "cost_usd": 0.0, "in_tok": 0, "out_tok": 0})
        for c in data.get("calls", []):
            day = c.get("ts", "")[:10]
            by_day[day]["calls"] += 1
            by_day[day]["cost_usd"] = round(by_day[day]["cost_usd"] + c.get("cost_usd", 0), 6)
            by_day[day]["in_tok"] += c.get("in_tok", 0)
            by_day[day]["out_tok"] += c.get("out_tok", 0)
        data["by_day"] = [{"date": k, **v} for k, v in sorted(by_day.items(), reverse=True)]
        # Coût en euros (1 USD ~ 0.92 EUR)
        data["total_cost_eur"] = round(data.get("total_cost_usd", 0) * 0.92, 4)
        return jsonify({"success": True, **data})
    except Exception as e:
        logger.error(f"[costs] erreur: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/rdvs', methods=['GET'])
def get_rdvs():
    """Retourne tous les RDV confirmés par l'agent (depuis les fichiers conversations/)."""
    from pathlib import Path as _P
    import json as _j
    conv_dir = _P('/data/.openclaw/workspace/vianova-agent/conversations')
    rdvs = []
    try:
        for f in sorted(conv_dir.glob('*.json'), key=lambda x: x.stat().st_mtime, reverse=True):
            try:
                data = _j.loads(f.read_text())
                stage = data.get('stage', '')
                if stage not in ('rdv_confirme', 'clos'):
                    continue
                info = data.get('lead_info', {})
                creneau = info.get('creneau_en_attente', '')
                if not creneau:
                    continue
                phone = data.get('phone', f.stem)
                # Parser le créneau "lundi 17/03 à 9h00"
                import re as _re
                date_m = _re.search(r'(\d{1,2})/(\d{1,2})', creneau)
                heure_m = _re.search(r'(\d{1,2})h(\d{0,2})', creneau)
                iso_date = None
                if date_m and heure_m:
                    from datetime import datetime as _dt
                    day, month = int(date_m.group(1)), int(date_m.group(2))
                    hour = int(heure_m.group(1))
                    minute = int(heure_m.group(2)) if heure_m.group(2) else 0
                    year = _dt.now().year
                    try:
                        iso_date = _dt(year, month, day, hour, minute).isoformat()
                    except Exception:
                        pass
                lead = leads_manager.get_lead(phone) or {}
                rdvs.append({
                    'phone': phone,
                    'prenom': info.get('prenom') or lead.get('prenom', ''),
                    'nom': lead.get('nom', ''),
                    'ville': info.get('ville') or lead.get('ville', ''),
                    'typo': info.get('typo') or lead.get('typologie', ''),
                    'email': info.get('email', ''),
                    'creneau': creneau,
                    'iso_date': iso_date,
                    'stage': stage,
                    'last_interaction': data.get('last_interaction', ''),
                })
            except Exception:
                continue
        # Trier par date du RDV
        rdvs.sort(key=lambda x: x.get('iso_date') or '', reverse=False)
        return jsonify({'success': True, 'rdvs': rdvs})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ==================== GOOGLE CALENDAR OAUTH ====================
from pathlib import Path as _OAuthPath

GOOGLE_CREDS_FILE   = _OAuthPath('/data/.openclaw/workspace/vianova-agent/google_credentials.json')
GOOGLE_TOKEN_FILE   = _OAuthPath('/data/.openclaw/workspace/vianova-agent/token.json')
GOOGLE_OAUTH_SCOPES = [
    'https://www.googleapis.com/auth/calendar',
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive',
]
OAUTH_REDIRECT_URI = 'https://vianova.meninbot.com/oauth/callback'

MIIZY_CREDS_FILE     = _OAuthPath('/data/.openclaw/workspace/vianova-agent/miizy_credentials.json')
MIIZY_TOKEN_FILE     = _OAuthPath('/data/.openclaw/workspace/vianova-agent/miizy_token.json')
MIIZY_OAUTH_SCOPES   = ['https://www.googleapis.com/auth/calendar']
MIIZY_REDIRECT_URI   = 'https://miizy.meninbot.com/miizy/oauth/callback'

@app.route('/oauth/start', methods=['GET'])
def oauth_start():
    """Lance le flow OAuth2 Google — redirige vers Google pour autorisation."""
    try:
        import os as _os
        _os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
        from google_auth_oauthlib.flow import Flow
        flow = Flow.from_client_secrets_file(
            str(GOOGLE_CREDS_FILE),
            scopes=GOOGLE_OAUTH_SCOPES,
            redirect_uri=OAUTH_REDIRECT_URI,
        )
        auth_url, state = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='false',
            prompt='consent',
        )
        # Stocker l'objet flow ENTIER pour préserver le code_verifier PKCE
        # (stocker seulement le state ne suffit pas : un nouveau Flow recréé en callback
        #  n'a pas le code_verifier d'origine → invalid_grant)
        app._oauth_flow = flow
        from flask import redirect as _redirect
        return _redirect(auth_url)
    except Exception as e:
        return f"<h2>Erreur OAuth start</h2><pre>{e}</pre>", 500


@app.route('/oauth/callback', methods=['GET'])
def oauth_callback():
    """Reçoit le code Google, échange contre un token et sauvegarde token.json."""
    try:
        import os as _os
        _os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'  # HTTPS géré par Traefik

        # Réutiliser le flow d'origine (préserve le code_verifier PKCE)
        flow = getattr(app, '_oauth_flow', None)
        if flow is None:
            return ("<h2>Session OAuth expirée</h2>"
                    "<p><a href='/oauth/start'>Recommencer</a></p>"), 400

        flow.fetch_token(authorization_response=request.url.replace('http://', 'https://'))
        creds = flow.credentials
        app._oauth_flow = None  # Nettoyer

        token_data = {
            'token':         creds.token,
            'refresh_token': creds.refresh_token,
            'token_uri':     creds.token_uri,
            'client_id':     creds.client_id,
            'client_secret': creds.client_secret,
            'scopes':        list(creds.scopes),
        }
        GOOGLE_TOKEN_FILE.write_text(json.dumps(token_data, indent=2))
        logger.info("✅ Google Calendar token sauvegardé avec succès")

        return """
        <html><body style="font-family:sans-serif;text-align:center;padding:60px;">
        <h2 style="color:#22543d;">✅ Google Calendar connecté !</h2>
        <p>Le token a été sauvegardé. L'agent peut maintenant créer des RDV Calendar.</p>
        <p><a href="/">← Retour au dashboard</a></p>
        </body></html>
        """
    except Exception as e:
        logger.error(f"OAuth callback erreur: {e}")
        return f"<h2>Erreur OAuth callback</h2><pre>{e}</pre>", 500


@app.route('/oauth/status', methods=['GET'])
def oauth_status():
    """Vérifie si le token Calendar est présent et valide."""
    try:
        if not GOOGLE_TOKEN_FILE.exists():
            return jsonify({'connected': False, 'reason': 'token.json absent'})
        data = json.loads(GOOGLE_TOKEN_FILE.read_text())
        scopes = data.get('scopes', [])
        has_calendar = any('calendar' in s for s in scopes)
        has_refresh = bool(data.get('refresh_token'))
        # Récupérer l'email du compte connecté
        email = ''
        if has_calendar and has_refresh:
            try:
                from google.oauth2.credentials import Credentials
                from googleapiclient.discovery import build
                creds = Credentials(
                    token=data.get('token'),
                    refresh_token=data.get('refresh_token'),
                    token_uri=data.get('token_uri'),
                    client_id=data.get('client_id'),
                    client_secret=data.get('client_secret'),
                    scopes=scopes,
                )
                svc = build('calendar', 'v3', credentials=creds)
                cal = svc.calendars().get(calendarId='primary').execute()
                email = cal.get('id', '')
            except Exception:
                pass
        return jsonify({
            'connected': has_calendar and has_refresh,
            'has_calendar_scope': has_calendar,
            'has_refresh_token': has_refresh,
            'scopes': scopes,
            'email': email,
        })
    except Exception as e:
        return jsonify({'connected': False, 'reason': str(e)})


# ==================== MIIZY OAUTH ROUTES ====================

@app.route('/miizy/oauth/start', methods=['GET'])
def miizy_oauth_start():
    """Lance le flow OAuth2 Google pour le compte Miizy (Alex)."""
    try:
        import os as _os
        _os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
        from google_auth_oauthlib.flow import Flow
        flow = Flow.from_client_secrets_file(
            str(MIIZY_CREDS_FILE),
            scopes=MIIZY_OAUTH_SCOPES,
            redirect_uri=MIIZY_REDIRECT_URI,
        )
        auth_url, _ = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='false',
            prompt='consent',
        )
        app._miizy_oauth_flow = flow
        from flask import redirect as _redirect
        return _redirect(auth_url)
    except Exception as e:
        return f"<h2>Erreur OAuth Miizy start</h2><pre>{e}</pre>", 500

@app.route('/miizy/oauth/callback', methods=['GET'])
def miizy_oauth_callback():
    """Reçoit le code Google Miizy, échange contre un token et sauvegarde miizy_token.json."""
    try:
        import os as _os
        _os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
        flow = getattr(app, '_miizy_oauth_flow', None)
        if flow is None:
            return ("<h2>Session OAuth Miizy expirée</h2>"
                    "<p><a href='/miizy/oauth/start'>Recommencer</a></p>"), 400
        flow.fetch_token(authorization_response=request.url.replace('http://', 'https://'))
        creds = flow.credentials
        app._miizy_oauth_flow = None
        token_data = {
            'token':         creds.token,
            'refresh_token': creds.refresh_token,
            'token_uri':     creds.token_uri,
            'client_id':     creds.client_id,
            'client_secret': creds.client_secret,
            'scopes':        list(creds.scopes),
        }
        MIIZY_TOKEN_FILE.write_text(json.dumps(token_data, indent=2))
        logger.info("✅ Miizy Google Calendar token sauvegardé")
        return """
        <html><body style="font-family:sans-serif;text-align:center;padding:60px;">
        <h2 style="color:#22543d;">✅ Google Calendar Miizy connecté !</h2>
        <p>Le token a été sauvegardé. Alex peut maintenant proposer des créneaux réels.</p>
        <p><a href="/">← Retour au dashboard</a></p>
        </body></html>
        """
    except Exception as e:
        logger.error(f"OAuth Miizy callback erreur: {e}")
        return f"<h2>Erreur OAuth Miizy callback</h2><pre>{e}</pre>", 500

@app.route('/miizy/debug/conversations', methods=['GET'])
def miizy_debug_conversations():
    """Debug endpoint — vérifie la connexion Evolution API Miizy et liste les chats bruts."""
    import requests as req
    cfg = _miizy_evo_cfg
    result = {
        'config': {
            'base_url': cfg.get('base_url'),
            'instance_name': cfg.get('instance_name'),
            'api_key_prefix': cfg.get('api_key', '')[:8] + '...',
        }
    }
    # Test connexion instance
    try:
        headers = {'apikey': cfg['api_key'], 'Content-Type': 'application/json'}
        r = req.get(f"{cfg['base_url']}/instance/fetchInstances", headers=headers, timeout=8)
        result['instances_status'] = r.status_code
        instances = r.json() if r.status_code < 400 else []
        names = [i.get('instance', {}).get('instanceName') or i.get('name') for i in (instances if isinstance(instances, list) else [])]
        result['instances'] = names
    except Exception as e:
        result['instances_error'] = str(e)
    # Test findChats
    try:
        headers = {'apikey': cfg['api_key'], 'Content-Type': 'application/json'}
        r = req.post(f"{cfg['base_url']}/chat/findChats/{cfg['instance_name']}", headers=headers, json={}, timeout=8)
        result['findChats_status'] = r.status_code
        raw = r.json()
        result['findChats_type'] = type(raw).__name__
        if isinstance(raw, list):
            result['findChats_count'] = len(raw)
            result['findChats_sample'] = raw[:2]
        elif isinstance(raw, dict):
            result['findChats_keys'] = list(raw.keys())
            for k in ('chats', 'data', 'records'):
                if k in raw:
                    result['findChats_count'] = len(raw[k])
                    result['findChats_sample'] = raw[k][:2]
                    break
            else:
                result['findChats_raw'] = raw
        else:
            result['findChats_raw'] = str(raw)
    except Exception as e:
        result['findChats_error'] = str(e)
    # Leads Miizy
    try:
        leads = miizy_leads_manager.list_leads()
        result['miizy_leads_count'] = len(leads)
        result['miizy_leads_sample'] = [{'phone': l.get('phone'), 'state': l.get('state')} for l in leads[:3]]
    except Exception as e:
        result['miizy_leads_error'] = str(e)
    return jsonify(result)


@app.route('/miizy/oauth/status', methods=['GET'])
def miizy_oauth_status():
    """Vérifie si le token Calendar Miizy est présent et valide."""
    try:
        if not MIIZY_TOKEN_FILE.exists():
            return jsonify({'connected': False, 'reason': 'miizy_token.json absent'})
        data = json.loads(MIIZY_TOKEN_FILE.read_text())
        has_calendar = any('calendar' in s for s in data.get('scopes', []))
        has_refresh  = bool(data.get('refresh_token'))
        email = ''
        if has_calendar and has_refresh:
            try:
                from google.oauth2.credentials import Credentials
                from googleapiclient.discovery import build
                creds = Credentials(
                    token=data.get('token'), refresh_token=data.get('refresh_token'),
                    token_uri=data.get('token_uri'), client_id=data.get('client_id'),
                    client_secret=data.get('client_secret'), scopes=data.get('scopes'),
                )
                svc = build('calendar', 'v3', credentials=creds)
                cal = svc.calendars().get(calendarId='primary').execute()
                email = cal.get('id', '')
            except Exception:
                pass
        return jsonify({'connected': has_calendar and has_refresh, 'email': email})
    except Exception as e:
        return jsonify({'connected': False, 'reason': str(e)})


@app.route('/oauth/disconnect', methods=['POST'])
def oauth_disconnect():
    """Supprime le token Google Calendar (déconnexion)."""
    try:
        if GOOGLE_TOKEN_FILE.exists():
            GOOGLE_TOKEN_FILE.unlink()
            logger.info("🔌 Google Calendar déconnecté — token.json supprimé")
        app._oauth_flow = None
        return jsonify({'success': True, 'message': 'Déconnecté de Google Calendar'})
    except Exception as e:
        logger.error(f"OAuth disconnect erreur: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/calendar/config', methods=['GET'])
def get_calendar_config():
    """Retourne le calendar_id configuré."""
    try:
        config_path = _OAuthPath(CONFIG_FILE)
        config = json.loads(config_path.read_text()) if config_path.exists() else {}
        calendar_id = config.get('google', {}).get('calendar_id', '')
        return jsonify({'calendar_id': calendar_id})
    except Exception as e:
        return jsonify({'calendar_id': '', 'error': str(e)})


@app.route('/api/calendar/config', methods=['POST'])
def set_calendar_config():
    """Sauvegarde le calendar_id dans config.json."""
    try:
        body = request.get_json(force=True) or {}
        calendar_id = body.get('calendar_id', '').strip()
        if not calendar_id:
            return jsonify({'success': False, 'error': 'calendar_id vide'}), 400

        config_path = _OAuthPath(CONFIG_FILE)
        config = json.loads(config_path.read_text()) if config_path.exists() else {}
        config.setdefault('google', {})['calendar_id'] = calendar_id
        config_path.write_text(json.dumps(config, indent=2, ensure_ascii=False))
        logger.info(f"✅ calendar_id mis à jour: {calendar_id}")
        return jsonify({'success': True, 'calendar_id': calendar_id})
    except Exception as e:
        logger.error(f"set_calendar_config erreur: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ==================== AGENT SCENARIOS ====================

@app.route('/api/agent/scenarios', methods=['GET'])
def get_agent_scenarios():
    """Récupère les scénarios éditables de l'agent"""
    try:
        scenarios_path = '/data/.openclaw/workspace/vianova-agent/agent_scenarios.json'
        if os.path.exists(scenarios_path):
            with open(scenarios_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return jsonify({"success": True, "scenarios": data.get("scenarios", {})})
        return jsonify({"success": True, "scenarios": {}})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/agent/scenarios', methods=['PUT'])
def update_agent_scenarios():
    """Met à jour les scénarios éditables de l'agent"""
    try:
        data = request.json
        scenarios_path = '/data/.openclaw/workspace/vianova-agent/agent_scenarios.json'
        existing = {}
        if os.path.exists(scenarios_path):
            with open(scenarios_path, 'r', encoding='utf-8') as f:
                existing = json.load(f)
        # Merge: update only provided scenarios
        if 'scenarios' not in existing:
            existing['scenarios'] = {}
        for key, val in data.get('scenarios', {}).items():
            if key in existing['scenarios']:
                existing['scenarios'][key]['responses'] = val.get('responses', existing['scenarios'][key].get('responses', []))
            else:
                existing['scenarios'][key] = val
        with open(scenarios_path, 'w', encoding='utf-8') as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)
        logger.info("✅ Scénarios agent mis à jour")
        return jsonify({"success": True})
    except Exception as e:
        logger.error(f"Error updating scenarios: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ==================== MIIZY WEBHOOK ====================

_miizy_buffer: Dict[str, Dict] = {}
_miizy_buffer_lock = threading.Lock()

def _miizy_store_manual_message(phone: str, text: str, from_me: bool):
    """Stocke un message manuel (commercial ou prospect quand bot pausé) dans Redis pour affichage dashboard."""
    try:
        key = f"miizy:manual:{phone}"
        raw = redis_client.client.get(key)
        msgs = json.loads(raw) if raw else []
        msgs.append({
            "text": text,
            "fromMe": from_me,
            "timestamp": int(datetime.now().timestamp()),
        })
        if len(msgs) > 500:
            msgs = msgs[-500:]
        redis_client.client.set(key, json.dumps(msgs))
    except Exception as e:
        logger.warning(f"_miizy_store_manual_message error: {e}")

def _process_miizy_buffered(phone: str):
    """Traite les messages Miizy accumulés dans le buffer."""
    with _miizy_buffer_lock:
        buf = _miizy_buffer.pop(phone, None)
    if not buf:
        return

    texts = buf["texts"]
    ids = buf["ids"]
    aggregated_text = "\n".join(texts)
    primary_id = ids[0] if ids else ""

    logger.info(f"[Miizy] Buffer flush {phone}: {len(texts)} msg(s) -> '{aggregated_text[:80]}'")

    try:
        from miizy_agent import MiizyAgent
        # Vérifier si le bot est désactivé (prise en main humaine) avant de répondre
        try:
            lead = miizy_leads_manager.get_lead(phone)
            if lead and (lead.get("state") == "pause" or not lead.get("ai_enabled", True)):
                logger.info(f"[Miizy] Bot désactivé pour {phone} — réponse annulée")
                return
        except Exception:
            pass

        agent = MiizyAgent(phone, redis_client.client)

        # Initialiser le prénom depuis la fiche lead si disponible
        try:
            lead = miizy_leads_manager.get_lead(phone)
            if lead:
                prenom = lead.get("prenom", "") or ""
                if prenom:
                    agent.set_prenom(prenom)
        except Exception:
            pass

        reply1, reply2 = agent.process_message(aggregated_text, primary_id)
        logger.info(f"[Miizy] Réponse: '{str(reply1)[:80]}'")

        if reply1:
            import time as _time
            import re as _re
            _send_cache = getattr(app, '_miizy_send_cache', {})
            app._miizy_send_cache = _send_cache
            cache_key = f"{phone}:{(reply1 + reply2).strip()}"
            now_ts = _time.time()
            if cache_key in _send_cache and now_ts - _send_cache[cache_key] < 10:
                logger.warning(f"[Miizy][dedup] message identique bloqué < 10s")
            else:
                _send_cache[cache_key] = now_ts
                # Choisir l'instance Evolution selon le commercial assigné au lead
                _lead_comm = 'adam'
                try:
                    _l = miizy_leads_manager.get_lead(phone)
                    if _l:
                        _lead_comm = _l.get('commercial_id', 'adam') or 'adam'
                except Exception:
                    pass
                _evo_to_use = _get_commercial_evo(_lead_comm)
                all_parts = []
                for _msg in [reply1, reply2]:
                    if _msg:
                        all_parts.extend(_split_human(_msg))
                for _i, _part in enumerate(all_parts):
                    if _i == 0:
                        _delay = _wait_read_then_type(phone, _part)
                    else:
                        _pause = min(2 + len(all_parts[_i - 1]) // 60, 5)
                        _time.sleep(_pause)
                        _delay = _calc_typing_delay(_part, min_s=2.0, max_s=6.0)
                    _evo_to_use.send_text(phone, _part, delay=_delay)

    except Exception as e:
        logger.error(f"[Miizy] Erreur buffer {phone}: {e}")
        import traceback; traceback.print_exc()


@app.route('/miizy/webhook/whatsapp', methods=['POST'])
def miizy_webhook_whatsapp():
    """Webhook WhatsApp pour l'agent Miizy (toutes instances commerciaux)."""
    try:
        data = request.get_json(silent=True) or {}
        event = data.get("event", "")

        if "messages.upsert" not in event:
            return jsonify({"status": "ignored"}), 200

        # Détecter quel commercial a reçu le message via le nom d'instance
        _incoming_instance = data.get("instance", "") or data.get("instanceName", "")
        _incoming_commercial = _instance_name_to_commercial(_incoming_instance)

        msg_data = data.get("data", {})
        key = msg_data.get("key", {})

        if key.get("fromMe"):
            raw_jid = key.get("remoteJid", "")
            alt_jid = key.get("remoteJidAlt", "")
            jid = alt_jid if alt_jid and "@s.whatsapp.net" in alt_jid else raw_jid
            phone_fm = _normalize_phone_number(jid.split("@")[0])
            if phone_fm:
                try:
                    lead = miizy_leads_manager.get_lead(phone_fm)
                    if lead and (lead.get("state") != "pause" or lead.get("ai_enabled", True)):
                        miizy_leads_manager.update_lead(phone_fm, {"state": "pause", "etat": "pause", "ai_enabled": False})
                except Exception as _e:
                    pass
                # Sauvegarder le message du commercial pour affichage dans le dashboard
                try:
                    _msg_body = msg_data.get("message", {}) or {}
                    _msg_text = (_msg_body.get("conversation") or
                                 (_msg_body.get("extendedTextMessage") or {}).get("text") or "").strip()
                    if _msg_text:
                        _miizy_store_manual_message(phone_fm, _msg_text, from_me=True)
                except Exception:
                    pass
            return jsonify({"status": "from_me_pause"}), 200

        raw_jid = key.get("remoteJid", "")
        alt_jid = key.get("remoteJidAlt", "")
        jid = alt_jid if alt_jid and "@s.whatsapp.net" in alt_jid else raw_jid
        phone = _normalize_phone_number(jid.split("@")[0])

        if not phone:
            return jsonify({"status": "ignored", "reason": "no_phone"}), 200

        message_body = msg_data.get("message", {})
        text = (message_body.get("conversation")
                or message_body.get("extendedTextMessage", {}).get("text")
                or "").strip()

        if not text:
            return jsonify({"status": "ignored", "reason": "no_text"}), 200

        msg_id = key.get("id", "")
        logger.info(f"[Miizy] WEBHOOK message de {phone}: '{text[:80]}'")

        # Marquer comme lu
        def _miizy_mark_read(jid, mid):
            try:
                import requests as _req
                _headers = {'apikey': _miizy_evo_cfg['api_key'], 'Content-Type': 'application/json'}
                _req.post(
                    f"{_miizy_evo_cfg['base_url']}/chat/markMessageAsRead/{_miizy_evo_cfg['instance_name']}",
                    headers=_headers,
                    json={"readMessages": [{"remoteJid": jid, "fromMe": False, "id": mid}]},
                    timeout=8
                )
            except Exception:
                pass
        _jid_m = jid if '@' in jid else f"{phone}@s.whatsapp.net"
        threading.Thread(target=_miizy_mark_read, args=(_jid_m, msg_id), daemon=True).start()

        # Human takeover Miizy
        try:
            lead = miizy_leads_manager.get_lead(phone)
            if lead and lead.get("state") == "pause":
                # Sauvegarder la réponse du prospect pour affichage dashboard
                try:
                    _miizy_store_manual_message(phone, text, from_me=False)
                except Exception:
                    pass
                return jsonify({"status": "paused"}), 200
        except Exception:
            pass

        # Créer le lead s'il n'existe pas encore (prospect qui répond sans avoir été importé)
        try:
            if not miizy_leads_manager.get_lead(phone):
                miizy_leads_manager.add_lead({
                    "phone": phone,
                    "state": "envoye",
                    "source": "whatsapp_reply",
                    "created_at": datetime.now().isoformat(),
                })
        except Exception:
            pass

        # Mettre à jour last_message_at
        try:
            miizy_leads_manager.update_lead(phone, {"last_message_at": datetime.now().isoformat()})
        except Exception:
            pass

        # Si le lead n'a pas encore de commercial_id, on lui attribue celui détecté
        if _incoming_commercial and _incoming_commercial != 'adam':
            try:
                _l = miizy_leads_manager.get_lead(phone)
                if _l and not _l.get('commercial_id'):
                    miizy_leads_manager.update_lead(phone, {'commercial_id': _incoming_commercial})
            except Exception:
                pass

        # Buffer Miizy
        with _miizy_buffer_lock:
            if phone in _miizy_buffer:
                _miizy_buffer[phone]["timer"].cancel()
                _miizy_buffer[phone]["texts"].append(text)
                _miizy_buffer[phone]["ids"].append(msg_id)
            else:
                _miizy_buffer[phone] = {"texts": [text], "ids": [msg_id], "timer": None}
            timer = threading.Timer(MIIZY_BUFFER_DELAY, _process_miizy_buffered, args=[phone])
            timer.daemon = True
            _miizy_buffer[phone]["timer"] = timer
            timer.start()

        return jsonify({"status": "buffered", "delay": MIIZY_BUFFER_DELAY}), 200

    except Exception as e:
        logger.error(f"[Miizy] Erreur webhook: {e}")
        return jsonify({"status": "error", "error": str(e)}), 500


# Auto-miroir : enregistrer /miizy/api/* pour toutes les routes /api/* existantes
def _register_miizy_api_mirrors():
    for rule in list(app.url_map.iter_rules()):
        if rule.rule.startswith('/api/'):
            miizy_path = '/miizy' + rule.rule
            endpoint_name = rule.endpoint + '__miizy'
            view_fn = app.view_functions[rule.endpoint]
            methods = [m for m in rule.methods if m not in ('HEAD', 'OPTIONS')]
            try:
                app.add_url_rule(miizy_path, endpoint_name, view_fn, methods=methods)
            except Exception:
                pass

_register_miizy_api_mirrors()


# ==================== AUTO-ADVANCE LEAD STATES ====================

# États "en conversation active" → jamais touchés par l'avancement auto
_RESPONDED_STATES = {
    'rdv_propose', 'attente_email', 'attente_creneau', 'confirme_creneau',
    'relance_creneau', 'rdv_confirme', 'attente_trouve', 'waiting_info',
    'nouveaux_criteres',
}
# États éligibles à l'avancement automatique (envoyé mais pas répondu)
_SENT_STATES = {'envoye', 'relance_24h', 'relance_72h'}


def _run_advance_check():
    """Avance les états des leads non-répondants selon le temps écoulé depuis sent_at."""
    import time as _t
    now = datetime.now()
    try:
        all_leads = leads_manager.list_leads()
    except Exception as _e:
        logger.error(f"[auto_advance] list_leads erreur: {_e}")
        return
    advanced = 0
    for lead in all_leads:
        state = (lead.get('state') or lead.get('etat') or 'initial').lower()
        if state in _RESPONDED_STATES or state in ('clos', 'fin_campagne', 'initial',
                                                    'message_a_envoyer', 'non_whatsapp'):
            continue
        if state not in _SENT_STATES:
            continue
        sent_at = lead.get('sent_at')
        if not sent_at:
            continue
        try:
            sent_time = datetime.fromisoformat(sent_at)
            hours = (now - sent_time).total_seconds() / 3600
            phone = lead.get('phone') or lead.get('telephone')
            if not phone:
                continue
            if hours >= 80 and state != 'fin_campagne':
                leads_manager.update_lead(phone, {'state': 'fin_campagne', 'etat': 'fin_campagne'})
                logger.info(f"[auto_advance] {phone} → fin_campagne ({hours:.0f}h)")
                advanced += 1
            elif hours >= 72 and state not in ('fin_campagne', 'relance_72h'):
                leads_manager.update_lead(phone, {'state': 'relance_72h', 'etat': 'relance_72h'})
                logger.info(f"[auto_advance] {phone} → relance_72h ({hours:.0f}h)")
                advanced += 1
            elif hours >= 24 and state == 'envoye':
                leads_manager.update_lead(phone, {'state': 'relance_24h', 'etat': 'relance_24h'})
                logger.info(f"[auto_advance] {phone} → relance_24h ({hours:.0f}h)")
                advanced += 1
        except Exception as _e:
            logger.error(f"[auto_advance] lead {lead.get('phone')}: {_e}")
    if advanced:
        logger.info(f"[auto_advance] {advanced} lead(s) avancé(s) automatiquement")


def _auto_advance_loop():
    """Thread daemon — tourne toutes les heures pour avancer les états leads."""
    import time as _t
    # Première vérification immédiate au démarrage
    _run_advance_check()
    while True:
        _t.sleep(3600)
        _run_advance_check()


_advance_thread = threading.Thread(target=_auto_advance_loop, daemon=True)
_advance_thread.start()
logger.info("✅ Thread auto-advance lead states démarré (vérification toutes les heures)")


# ==================== TRAINING ROUTES ====================

TRAINING_PHONE = "33000000000"
MIIZY_TRAINING_PHONE = "33000000001"

def _require_auth_training(f):
    """Decorator : training routes nécessitent admin."""
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('user_email'):
            return jsonify({'error': 'Non authentifié'}), 401
        if session.get('user_role') not in ('admin', 'daniel'):
            return jsonify({'error': 'Accès refusé'}), 403
        return f(*args, **kwargs)
    return decorated

@app.route('/api/training/history', methods=['GET'])
@_require_auth_training
def training_history():
    """Retourne l'historique de la conversation d'entraînement."""
    try:
        from conversation_memory import ConversationMemory
        mem = ConversationMemory(TRAINING_PHONE)
        messages = mem.data.get('messages', [])
        lead_info = mem.data.get('lead_info', {})
        stage = mem.get_stage()
        return jsonify({
            'messages': messages,
            'stage': stage,
            'lead_info': lead_info
        })
    except Exception as e:
        logger.error(f"[training/history] {e}")
        return jsonify({'messages': [], 'stage': 'initial', 'lead_info': {}})

@app.route('/api/training/message', methods=['POST'])
@_require_auth_training
def training_message():
    """Traite un message de l'utilisateur à travers l'agent Vianova (mode entraînement)."""
    try:
        body = request.get_json() or {}
        user_msg = (body.get('message') or '').strip()
        if not user_msg:
            return jsonify({'error': 'Message vide'}), 400

        from agent_ia_minimal import VianovaAgent
        agent = VianovaAgent(TRAINING_PHONE)
        response, extra = agent.process_message(user_msg)
        agent.memory.save()

        stage = agent.memory.get_stage()
        lead_info = agent.memory.data.get('lead_info', {})

        return jsonify({
            'response': response,
            'extra': extra or '',
            'stage': stage,
            'lead_info': lead_info
        })
    except Exception as e:
        logger.error(f"[training/message] {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@app.route('/api/training/campaign', methods=['POST'])
@_require_auth_training
def training_campaign():
    """Simule l'envoi du premier message de campagne (send_opening_message)."""
    try:
        body = request.get_json() or {}
        prenom = (body.get('prenom') or 'Test').strip()
        ville = (body.get('ville') or 'Paris').strip()
        typo = (body.get('typo') or 'T2').strip()
        date_contact = (body.get('date_contact') or '').strip() or datetime.now().strftime('%d/%m/%Y')

        from agent_ia_minimal import VianovaAgent
        from conversation_memory import ConversationMemory

        # Reset d'abord pour partir d'un état vierge
        mem = ConversationMemory(TRAINING_PHONE)
        mem.data = {
            'messages': [],
            'stage': 'initial',
            'lead_info': {
                'prenom': prenom,
                'ville': ville,
                'typo': typo,
                'typologie': typo,
                'date_dernier_contact': date_contact
            }
        }
        mem.save()

        # Générer et sauvegarder le message d'ouverture
        agent = VianovaAgent(TRAINING_PHONE)
        template_text = body.get('template_text') or None
        if template_text:
            opening = template_text.strip()
        else:
            opening = agent.send_opening_message()
        agent.memory.add_message('assistant', opening)
        agent.memory.set_stage('waiting_info')
        agent.memory.save()

        return jsonify({
            'message': opening,
            'stage': 'waiting_info',
            'lead_info': agent.memory.data.get('lead_info', {})
        })
    except Exception as e:
        logger.error(f"[training/campaign] {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@app.route('/api/training/reset', methods=['POST'])
@_require_auth_training
def training_reset():
    """Remet à zéro la conversation d'entraînement."""
    try:
        import pathlib
        conv_file = pathlib.Path(f"conversations/{TRAINING_PHONE}.json")
        if conv_file.exists():
            conv_file.unlink()
        return jsonify({'ok': True, 'message': 'Conversation réinitialisée'})
    except Exception as e:
        logger.error(f"[training/reset] {e}")
        return jsonify({'error': str(e)}), 500


# ==================== MIIZY TRAINING ROUTES ====================

@app.route('/miizy/api/training/history', methods=['GET'])
def miizy_training_history():
    """Retourne l'historique de la session d'entraînement Miizy."""
    if not session.get('user_email'):
        return jsonify({'error': 'Non authentifié'}), 401
    if session.get('user_role') not in ('admin', 'daniel'):
        return jsonify({'error': 'Accès refusé'}), 403
    try:
        from miizy_agent import MiizySession
        s = MiizySession(MIIZY_TRAINING_PHONE, redis_client.client)
        return jsonify({
            'messages': s.data.get('history', []),
            'step': s.step,
            'prenom': s.prenom,
        })
    except Exception as e:
        logger.error(f"[miizy_training/history] {e}")
        return jsonify({'messages': [], 'step': 'WAITING_NEUF_ANCIEN', 'prenom': ''})

@app.route('/miizy/api/training/message', methods=['POST'])
def miizy_training_message():
    """Traite un message via MiizyAgent (mode entraînement)."""
    if not session.get('user_email'):
        return jsonify({'error': 'Non authentifié'}), 401
    if session.get('user_role') not in ('admin', 'daniel'):
        return jsonify({'error': 'Accès refusé'}), 403
    try:
        body = request.get_json() or {}
        user_msg = (body.get('message') or '').strip()
        if not user_msg:
            return jsonify({'error': 'Message vide'}), 400
        from miizy_agent import MiizyAgent
        agent = MiizyAgent(MIIZY_TRAINING_PHONE, redis_client.client)
        response, extra = agent.process_message(user_msg)
        return jsonify({
            'response': response,
            'extra': extra or '',
            'step': agent.session.step,
        })
    except RuntimeError as e:
        if "CREDIT_INSUFFISANT" in str(e):
            return jsonify({'error': '💳 Crédit Anthropic insuffisant — rechargez votre compte sur console.anthropic.com pour que l\'agent puisse générer des réponses LLM.'}), 402
        logger.error(f"[miizy_training/message] {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500
    except Exception as e:
        logger.error(f"[miizy_training/message] {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@app.route('/miizy/api/training/campaign', methods=['POST'])
def miizy_training_campaign():
    """Simule le premier message de campagne Miizy."""
    if not session.get('user_email'):
        return jsonify({'error': 'Non authentifié'}), 401
    if session.get('user_role') not in ('admin', 'daniel'):
        return jsonify({'error': 'Accès refusé'}), 403
    try:
        body = request.get_json() or {}
        prenom = (body.get('prenom') or 'Test').strip()
        template_text = (body.get('template_text') or '').strip()

        from miizy_agent import MiizySession

        # Reset et init session
        s = MiizySession(MIIZY_TRAINING_PHONE, redis_client.client)
        s.data = {
            'phone': MIIZY_TRAINING_PHONE,
            'prenom': prenom,
            'step': 'WAITING_NEUF_ANCIEN',
            'branch': None,
            'history': [],
        }
        s.save()

        # Message d'ouverture
        if template_text:
            opening = template_text.replace('{Prenom}', prenom).replace('{prenom}', prenom)
        else:
            custom = {}
            try:
                if os.path.exists('miizy_templates.json'):
                    custom = json.load(open('miizy_templates.json', 'r', encoding='utf-8'))
            except Exception:
                pass
            tpl = custom.get('ouverture', "Bonjour {Prenom},\n\nVous travaillez sur du neuf, ou uniquement de l'ancien ?")
            opening = tpl.replace('{Prenom}', prenom).replace('{prenom}', prenom)

        s.add_history('assistant', opening)

        return jsonify({'message': opening, 'step': 'WAITING_NEUF_ANCIEN', 'prenom': prenom})
    except Exception as e:
        logger.error(f"[miizy_training/campaign] {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@app.route('/miizy/api/training/reset', methods=['POST'])
def miizy_training_reset():
    """Remet à zéro la session d'entraînement Miizy."""
    if not session.get('user_email'):
        return jsonify({'error': 'Non authentifié'}), 401
    if session.get('user_role') not in ('admin', 'daniel'):
        return jsonify({'error': 'Accès refusé'}), 403
    try:
        try:
            redis_client.client.delete(f"miizy:session:{MIIZY_TRAINING_PHONE}")
        except Exception:
            pass
        return jsonify({'ok': True, 'message': 'Session réinitialisée'})
    except Exception as e:
        logger.error(f"[miizy_training/reset] {e}")
        return jsonify({'error': str(e)}), 500


# ==================== DÉMARRAGE DES WORKERS ====================

# Moteur de séquences automatiques Miizy (Phase 1)
_miizy_sequence_engine_start()

# ==================== MAIN ====================

if __name__ == '__main__':
    logger.info("🚀 Starting Dashboard API on port 5000...")
    logger.info("📊 Dashboard: http://localhost:5000")
    app.run(host='0.0.0.0', port=5000, debug=False)
