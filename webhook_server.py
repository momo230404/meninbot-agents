#!/usr/bin/env python3
"""Serveur webhook pour réception messages WhatsApp"""
from flask import Flask, request, jsonify
import json
import logging
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from redis_client import RedisClient
from agent_ia import AgentIA

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

def load_config():
    with open('config.json', 'r') as f:
        return json.load(f)

config = load_config()
redis_client = RedisClient(config['redis']['url'])
agent = AgentIA(config, redis_client)

@app.route('/webhook/whatsapp', methods=['POST'])
def webhook_whatsapp():
    """Endpoint pour recevoir les messages WhatsApp"""
    try:
        data = request.get_json()
        logger.info(f"Message reçu: {data}")
        
        # Extraction des données
        phone = data.get('data', {}).get('key', {}).get('remoteJid', '').split('@')[0]
        message_body = data.get('data', {}).get('message', {}).get('conversation', '')
        message_id = data.get('data', {}).get('key', {}).get('id', '')
        
        if not phone or not message_body:
            return jsonify({"status": "ignored", "reason": "missing_data"}), 200
        
        # Anti-duplicats
        if redis_client.is_duplicate(phone, message_id):
            logger.info(f"Message dupliqué ignoré: {message_id}")
            return jsonify({"status": "ignored", "reason": "duplicate"}), 200
        
        # Traitement par l'agent
        response = agent.process_message(phone, message_body)
        
        return jsonify({"status": "processed", "response": response}), 200
        
    except Exception as e:
        logger.error(f"Erreur webhook: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok"}), 200

if __name__ == '__main__':
    logger.info("Démarrage serveur webhook sur port 8080")
    app.run(host='0.0.0.0', port=8080, debug=False)