#!/bin/bash
# 🚀 Quick Start - Migration Leads Vianova

set -e

echo "╔════════════════════════════════════════════════════════════╗"
echo "║     🚀 QUICK START - Migration Leads Vianova              ║"
echo "╚════════════════════════════════════════════════════════════╝"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

function print_step() {
    echo -e "\n${BLUE}▶${NC} $1"
}

function print_success() {
    echo -e "${GREEN}✅${NC} $1"
}

function print_warning() {
    echo -e "${YELLOW}⚠️${NC} $1"
}

function print_error() {
    echo -e "${RED}❌${NC} $1"
}

# Step 1: Check Python version
print_step "Vérification de Python..."
if ! command -v python3 &> /dev/null; then
    print_error "Python3 non trouvé. Veuillez installer Python 3.8+"
    exit 1
fi
PYTHON_VERSION=$(python3 --version | cut -d' ' -f2)
print_success "Python $PYTHON_VERSION détecté"

# Step 2: Check required files
print_step "Vérification des fichiers requis..."
REQUIRED_FILES=(
    "config.json"
    "dashboard_api.py"
    "redis_client.py"
    "leads_manager.py"
    "migration.py"
    "test_crud.py"
)

for file in "${REQUIRED_FILES[@]}"; do
    if [ -f "$file" ]; then
        print_success "$file"
    else
        print_error "$file manquant!"
        exit 1
    fi
done

# Step 3: Check Python dependencies
print_step "Vérification des dépendances Python..."
REQUIRED_PACKAGES=(
    "flask"
    "redis"
    "requests"
)

for package in "${REQUIRED_PACKAGES[@]}"; do
    if python3 -c "import $package" 2>/dev/null; then
        print_success "$package"
    else
        print_warning "$package non installé"
        echo "   Installez avec: pip install $package"
    fi
done

# Step 4: Show menu
print_step "Menu d'actions"
echo ""
echo "  1) Exécuter les tests CRUD (validation)"
echo "  2) Migrer les données depuis Google Sheets"
echo "  3) Démarrer l'API dashboard"
echo "  4) Afficher les exemples d'utilisation"
echo "  5) Afficher les statistiques"
echo "  6) Quitter"
echo ""
read -p "Choisissez une action (1-6): " choice

case $choice in
    1)
        print_step "Exécution des tests CRUD..."
        echo ""
        python3 test_crud.py
        ;;
    2)
        print_step "Migration depuis Google Sheets..."
        echo ""
        python3 migration.py
        ;;
    3)
        print_step "Démarrage de l'API dashboard..."
        echo ""
        print_warning "L'API sera disponible sur http://localhost:5000"
        echo ""
        python3 dashboard_api.py
        ;;
    4)
        print_step "Affichage des exemples d'utilisation..."
        echo ""
        echo "Assurez-vous que l'API est démarrée avant:"
        echo "  python3 dashboard_api.py"
        echo ""
        python3 example_api_usage.py
        ;;
    5)
        print_step "Statistiques des leads..."
        echo ""
        if [ -f "leads.json" ]; then
            python3 << 'EOF'
import json
with open("leads.json") as f:
    data = json.load(f)
    leads = data.get("leads", [])
    print(f"📊 Total leads: {len(leads)}")
    print(f"📅 Dernière synchro: {data.get('last_sync', 'N/A')}")
    
    # By state
    states = {}
    for lead in leads:
        state = lead.get("state", "unknown")
        states[state] = states.get(state, 0) + 1
    
    print("\n📋 Par état:")
    for state, count in sorted(states.items()):
        print(f"   {state}: {count}")
    
    # AI enabled
    ai_enabled = sum(1 for l in leads if l.get("ai_enabled", True))
    print(f"\n🤖 IA activée: {ai_enabled}/{len(leads)}")
EOF
        else
            print_warning "Fichier leads.json non trouvé"
            echo "   Exécutez d'abord la migration: option 2"
        fi
        ;;
    6)
        print_success "À bientôt!"
        exit 0
        ;;
    *)
        print_error "Option invalide"
        exit 1
        ;;
esac

echo ""
print_success "Action terminée!"
echo ""
