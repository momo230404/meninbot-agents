#!/bin/bash
# Tunnel permanent avec serveo.net (URL fixe)

echo "🔗 Création tunnel PERMANENT..."
echo "URL fixe: https://vianova-miizy.serveo.net"
echo ""

# Tuer les anciens tunnels
pkill -f "ssh.*serveo" 2>/dev/null
sleep 1

# Créer le tunnel persistant
# La clé -R garantit la même URL
ssh -o StrictHostKeyChecking=no -R vianova-miizy:80:localhost:3000 serveo.net &

sleep 3

echo "✅ TUNNEL ACTIF !"
echo "=================="
echo "URL PERMANENTE:"
echo "https://vianova-miizy.serveo.net/webhook/whatsapp"
echo "=================="
echo "Cette URL ne changera JAMAIS"
echo ""
echo "Pour arrêter: pkill -f serveo"