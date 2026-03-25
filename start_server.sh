#!/bin/bash
# Script de démarrage propre du webhook Vianova

cd /data/.openclaw/workspace/vianova-agent

# Tuer les anciens processus
pkill -9 -f "inbound.*py" 2>/dev/null
pkill -9 -f "lt --port" 2>/dev/null
sleep 2

export PYTHONPATH=/data/.openclaw/workspace/vianova-agent/.local/lib/python3.13/site-packages

# Démarrer le serveur sur port 3001
echo "🚀 Démarrage serveur webhook..."
nohup python3 inbound_fixed.py > /tmp/webhook_new.log 2>&1 &
sleep 3

# Démarrer le tunnel
echo "🔗 Création tunnel public..."
nohup lt --port 3000 --subdomain vianova-$(date +%s) > /tmp/tunnel.log 2>&1 &
sleep 5

# Afficher l'URL
echo ""
echo "✅ SERVEUR PRÊT !"
echo "=================="
grep -o "https://.*\.loca\.lt" /tmp/tunnel.log | head -1
echo "=================="

# Afficher la santé
curl -s http://localhost:3000/health
echo ""