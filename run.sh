#!/bin/bash

# Vianova WhatsApp Agent - Script de lancement

VIRTUAL_ENV="${VIRTUAL_ENV:-.venv}"
PYTHON="${VIRTUAL_ENV}/bin/python"

# Couleurs
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Vérification virtualenv
if [ ! -d "$VIRTUAL_ENV" ]; then
    log_info "Création virtualenv..."
    python3 -m venv "$VIRTUAL_ENV"
    log_info "Installation des dépendances..."
    "$VIRTUAL_ENV/bin/pip" install -r requirements.txt
    log_info "Installation google-auth (nécessaire)..."
    "$VIRTUAL_ENV/bin/pip" install google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client
fi

# Vérification credentials Google
if [ ! -f "client_secret_gdrive.json" ]; then
    log_warn "Fichier client_secret_gdrive.json manquant !"
    log_warn "Place-le dans /data/.openclaw/workspace/vianova-agent/"
    exit 1
fi

# Création dossier logs
mkdir -p logs

case "$1" in
    server)
        log_info "Démarrage serveur webhook sur port 8080..."
        PORT=8080 "$PYTHON" webhook_server.py
        ;;
    
    dashboard)
        log_info "Démarrage API Dashboard sur port 5000..."
        log_info "Ouvrir: http://localhost:5000/dashboard"
        "$PYTHON" dashboard_api.py
        ;;
    
    full)
        log_info "Démarrage COMPLET: webhook + dashboard API..."
        PORT=8080 "$PYTHON" webhook_server.py &
        WEBHOOK_PID=$!
        sleep 2
        log_info "Webhook lancé (PID: $WEBHOOK_PID)"
        
        "$PYTHON" dashboard_api.py &
        DASHBOARD_PID=$!
        log_info "Dashboard API lancé (PID: $DASHBOARD_PID)"
        
        echo "$WEBHOOK_PID" > logs/webhook.pid
        echo "$DASHBOARD_PID" > logs/dashboard.pid
        
        log_info "✅ Services lancés!"
        log_info "📊 Dashboard: http://localhost:5000/dashboard"
        log_info "🔗 Webhook: http://187.124.33.83:8080/webhook/whatsapp"
        
        wait
        ;;
    
    campaign|campain)
        log_info "Lancement campagne..."
        "$PYTHON" campain.py
        ;;
    
    dry-run)
        log_info "Test campagne (sans envoi)..."
        "$PYTHON" campain.py --dry-run
        ;;
    
    test-api)
        log_info "Test API Miizy (Lyon T2)..."
        "$PYTHON" -c "
import sys
sys.path.insert(0, 'tools')
from miizy_api import MiizyAPI
api = MiizyAPI('37|O9MtqGOSCJ6b6FNEmCW7cxmjh3B7HsIxLMr15G9I', 'https://miizy.com/miizy')
biens = api.search_stock('Lyon', 'T2')
print(f'Biens trouvés: {len(biens)}')
for b in biens[:3]:
    print(f' - {b.get(\"titre\", \"N/A\")}: {b.get(\"prix\", \"N/A\")}€')
"
        ;;
    
    status)
        log_info "=== État des services ==="
        if [ -f "logs/webhook.pid" ]; then
            PID=$(cat logs/webhook.pid)
            if kill -0 "$PID" 2>/dev/null; then
                log_info "✅ Webhook (PID: $PID) - ACTIF"
            else
                log_warn "❌ Webhook (PID: $PID) - ARRÊTÉ"
            fi
        else
            log_warn "⚠️  Webhook - Aucun PID trouvé"
        fi
        
        if [ -f "logs/dashboard.pid" ]; then
            PID=$(cat logs/dashboard.pid)
            if kill -0 "$PID" 2>/dev/null; then
                log_info "✅ Dashboard API (PID: $PID) - ACTIF"
            else
                log_warn "❌ Dashboard API (PID: $PID) - ARRÊTÉ"
            fi
        else
            log_warn "⚠️  Dashboard API - Aucun PID trouvé"
        fi
        ;;
    
    stop)
        log_info "Arrêt des services..."
        if [ -f "logs/webhook.pid" ]; then
            PID=$(cat logs/webhook.pid)
            kill "$PID" 2>/dev/null && log_info "✅ Webhook arrêté" || log_warn "Webhook déjà arrêté"
            rm -f logs/webhook.pid
        fi
        if [ -f "logs/dashboard.pid" ]; then
            PID=$(cat logs/dashboard.pid)
            kill "$PID" 2>/dev/null && log_info "✅ Dashboard API arrêté" || log_warn "Dashboard API déjà arrêté"
            rm -f logs/dashboard.pid
        fi
        ;;
    
    *)
        echo "Usage: ./run.sh {server|dashboard|full|campaign|dry-run|test-api|status|stop}"
        echo ""
        echo "Commandes principales:"
        echo " full       - Démarrer TOUT (webhook + dashboard)"
        echo " server     - Webhook uniquement (port 8080)"
        echo " dashboard  - API Dashboard uniquement (port 5000)"
        echo ""
        echo "Commandes de campagne:"
        echo " campaign   - Lancer campagne WhatsApp"
        echo " dry-run    - Tester campagne sans envoi"
        echo " test-api   - Tester API Miizy"
        echo ""
        echo "Gestion:"
        echo " status     - Vérifier état des services"
        echo " stop       - Arrêter tous les services"
        exit 1
        ;;
esac
