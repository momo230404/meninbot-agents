#!/usr/bin/env python3
"""
Serveur Webhook Inbound - Réception des messages WhatsApp
Sur port 3000 (souvent ouvert par défaut)
"""
import json
from flask import Flask, request, jsonify
from pathlib import Path

from agent_ia import VianovaAgent
from tools.evolution import send_conversation_messages, mark_as_read

app = Flask(__name__)

@app.route('/webhook/whatsapp', methods=['POST'])
def handle_whatsapp_webhook():
    """Endpoint principal pour recevoir les messages"""
    try:
        data = request.get_json()
        
        # DEBUG
        print(f"\n🔔 WEBHOOK REÇU: {json.dumps(data, indent=2)[:500]}")
        
        # Ignore si pas un message
        event = data.get("event", "")
        if "messages.upsert" not in event:
            return jsonify({"status": "ignored"}), 200
        
        message_data = data.get("data", {})
        key = message_data.get("key", {})
        
        # Ignore les messages envoyés par nous
        if key.get("fromMe"):
            return jsonify({"status": "from_me"}), 200
        
        phone = key.get("remoteJid", "").replace("@s.whatsapp.net", "").replace("@c.us", "")
        message = message_data.get("message", {})
        
        # Extrait le texte
        text = ""
        if "conversation" in message:
            text = message["conversation"]
        elif "extendedTextMessage" in message:
            text = message["extendedTextMessage"].get("text", "")
        
        print(f"📩 MESSAGE de {phone}: '{text}'")
        
        # Marque comme lu
        msg_id = key.get("id", "")
        mark_as_read(msg_id, phone)
        
        # Traitement IA
        agent = VianovaAgent(phone)
        reply1, reply2 = agent.process_message(text, msg_id)
        
        print(f"🤖 RÉPONSE: '{reply1[:50]}...' | '{reply2[:50] if reply2 else ''}'")
        
        # Envoi
        if reply1:
            messages = [r for r in [reply1, reply2] if r]
            result = send_conversation_messages(phone, messages)
            print(f"📤 ENVOI: {'✅' if result['success'] else '❌'}")
            return jsonify({"status": "success"}), 200
        
        return jsonify({"status": "no_reply"}), 200
        
    except Exception as e:
        print(f"💥 ERREUR: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error"}), 500

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "healthy", "port": 3000}), 200

if __name__ == '__main__':
    print("=" * 60)
    print("🚀 Webhook Vianova sur PORT 3000")
    print("URL: http://187.124.33.83:3000/webhook/whatsapp")
    print("=" * 60)
    app.run(host='0.0.0.0', port=3001, debug=False)