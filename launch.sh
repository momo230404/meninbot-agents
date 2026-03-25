#!/bin/bash
# Lancement complet avec tunnel Cloudflare

echo "🚀 Démarrage Agent Vianova..."
cd /data/.openclaw/workspace/vianova-agent

# Exports
export PYTHONPATH=/data/.openclaw/workspace/vianova-agent/.local/lib/python3.13/site-packages

# Tuer anciens
pkill -f "inbound.*py" 2>/dev/null
pkill -f cloudflared 2>/dev/null
sleep 2

# Lancer serveur
echo "📡 Démarrage serveur webhook..."
python3 inbound_fixed.py &
sleep 3

# Vérifier santé
if curl -s http://localhost:3000/health > /dev/null; then
    echo "✅ Serveur OK sur port 3000"
else
    echo "❌ Serveur non démarré"
    exit 1
fi

# Lancer tunnel Cloudflare
echo "🔗 Création tunnel Cloudflare..."
/tmp/cloudflared tunnel --url http://localhost:3000 &
sleep 8

# URL
echo ""
echo "========================================"
echo "🔗 URL PUBLIQUE WEBHOOK:"
grep -o "https://[a-z0-9-]*\.trycloudflare\.com" /tmp/cloudflare.log 2>/dev/null | head -1 | sed 's|$|/webhook/whatsapp|'
echo "========================================"
echo ""
echo "✅ Agent prêt !"
echo "  - Webhook: http://localhost:3000"
echo "  - Tunnel: Cloudflare (URL ci-dessus)"
echo ""
echo "⚠️  Cette URL est TEMPORAIRE (change au redémarrage)"
echo "   Pour URL permanente: ouvrir port 8080 dans Hostinger"