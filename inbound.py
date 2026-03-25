#!/usr/bin/env python3
"""
Serveur Webhook Inbound - Réception des messages WhatsApp
Remplace complètement le webhook N8N
"""
import json
import hmac
import hashlib
from flask import Flask, request, jsonify
from pathlib import Path

# Import modules locaux
from agent_ia import VianovaAgent
from tools.evolution import send_conversation_messages, mark_as_read

# Initialisation Flask
app = Flask(__name__)

# Chargement config
CONFIG = json.load(open(Path(__file__).parent / "config.json"))
WEBHOOK_SECRET = CONFIG["evolution_api"]["api_key"]


def verify_webhook_signature(request_data: bytes, signature: str = None) -> bool:
    """Vérifie la signature du webhook (si configurée)"""
    if not signature:
        return True
    expected = hmac.new(
        WEBHOOK_SECRET.encode(),
        request_data,
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def parse_inbound_message(data: dict) -> dict:
    """
    Parse le payload webhook Evolution API
    Retourne: {phone, message, message_id, type, timestamp}
    """
    try:
        # Format Evolution API webhook
        event_type = data.get("event", "")
        
        if "message" in event_type or "messages.upsert" in event_type:
            message_data = data.get("data", {})
            key = message_data.get("key", {})
            message = message_data.get("message", {})
            
            # Ignore les messages envoyés par nous-mêmes
            if key.get("fromMe"):
                return None
            
            phone = key.get("remoteJid", "").replace("@s.whatsapp.net", "").replace("@c.us", "")
            message_id = key.get("id", "")
            
            # Extrait le texte du message
            text = ""
            if "conversation" in message:
                text = message["conversation"]
            elif "extendedTextMessage" in message:
                text = message["extendedTextMessage"].get("text", "")
            elif "imageMessage" in message:
                text = "[Image reçue]"
            elif "documentMessage" in message:
                text = "[Document reçu]"
            
            return {
                "phone": phone,
                "message": text.strip(),
                "message_id": message_id,
                "type": "text",
                "timestamp": data.get("date_time", "")
            }
        
        return None
        
    except Exception as e:
        print(f"Erreur parsing: {e}")
        return None


@app.route('/webhook/whatsapp', methods=['POST'])
def handle_whatsapp_webhook():
    """
    Endpoint principal pour recevoir les messages WhatsApp
    """
    try:
        # Récupère les données
        data = request.get_json()
        
        if not data:
            return jsonify({"status": "error", "message": "No data"}), 400
        
        # Parse le message
        parsed = parse_inbound_message(data)
        
        if not parsed:
            # Message ignoré (de nous-mêmes ou format inconnu)
            return jsonify({"status": "ignored"}), 200
        
        phone = parsed["phone"]
        message = parsed["message"]
        message_id = parsed["message_id"]
        
        print(f"\n📩 Message reçu de {phone}: '{message[:50]}...'")
        
        # Marque comme lu rapidement
        mark_as_read(message_id, phone)
        
        # Process avec l'agent IA
        agent = VianovaAgent(phone)
        reply1, reply2 = agent.process_message(message, message_id)
        
        # Envoie la réponse
        if reply1:
            messages_to_send = [reply1]
            if reply2:
                messages_to_send.append(reply2)
            
            result = send_conversation_messages(phone, messages_to_send)
            
            if result["success"]:
                print(f"✅ Réponse envoyée à {phone}")
                return jsonify({"status": "success"}), 200
            else:
                print(f"❌ Échec envoi: {result.get('error')}")
                return jsonify({"status": "error"}), 500
        
        return jsonify({"status": "no_reply"}), 200
        
    except Exception as e:
        print(f"💥 Erreur webhook: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/webhook/status', methods=['POST'])
def handle_status_webhook():
    """
    Reçoit les mises à jour de statut (message delivered, read, etc.)
    """
    data = request.get_json()
    
    if data and "status" in data.get("event", ""):
        # Log les statuts si besoin
        pass
    
    return jsonify({"status": "ok"}), 200


@app.route('/health', methods=['GET'])
def health_check():
    """Health check pour Docker/superviseur"""
    return jsonify({
        "status": "healthy",
        "service": "vianova-agent-inbound"
    }), 200


@app.route('/', methods=['GET'])
def index():
    """Page d'accueil"""
    return jsonify({
        "service": "Vianova Agent - Inbound Webhook",
        "version": "1.0",
        "endpoints": {
            "/webhook/whatsapp": "Recevoir messages WhatsApp (POST)",
            "/webhook/status": "Recevoir statuts messages (POST)",
            "/health": "Health check (GET)"
        }
    }), 200


def run_server(host='0.0.0.0', port=3000, debug=False):
    """Démarre le serveur webhook"""
    print("=" * 50)
    print("🚀 Serveur Webhook Vianova démarré")
    print("=" * 50)
    print(f"📍 URL: http://{host}:{port}")
    print(f"📍 Webhook: http://{host}:{port}/webhook/whatsapp")
    print(f"📍 Health: http://{host}:{port}/health")
    print("-" * 50)
    
    app.run(host=host, port=port, debug=debug)


if __name__ == '__main__':
    # En production, utilisez gunicorn:
    # gunicorn -w 2 -b 0.0.0.0:8080 inbound:app
    run_server(port=8080, debug=False)