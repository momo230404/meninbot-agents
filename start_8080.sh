#!/bin/bash
cd /data/.openclaw/workspace/vianova-agent
export PYTHONPATH=/data/.openclaw/workspace/vianova-agent/.local/lib/python3.13/site-packages

# Kill old
pkill -f "inbound.*py" 2>/dev/null
pkill -f cloudflared 2>/dev/null
sleep 2

# Start on port 8080
python3 -c "
import sys
sys.path.insert(0, '/data/.openclaw/workspace/vianova-agent/.local/lib/python3.13/site-packages')
from flask import Flask, request, jsonify
from pathlib import Path
from agent_ia import VianovaAgent
from tools.evolution import send_conversation_messages, mark_as_read

app = Flask(__name__)

@app.route('/webhook/whatsapp', methods=['POST'])
def webhook():
    try:
        data = request.get_json()
        print(f\"\\n📩 WEBHOOK: {data}\")
        
        event = data.get('event', '')
        if 'messages.upsert' not in event:
            return jsonify({'status': 'ignored'})
        
        msg_data = data.get('data', {})
        key = msg_data.get('key', {})
        
        if key.get('fromMe'):
            return jsonify({'status': 'from_me'})
        
        phone = key.get('remoteJid', '').replace('@s.whatsapp.net', '').replace('@c.us', '')
        message = msg_data.get('message', {})
        text = message.get('conversation', '') or message.get('extendedTextMessage', {}).get('text', '')
        
        print(f\"\\n👤 {phone}: '{text}'\")
        
        mark_as_read(key.get('id'), phone)
        
        agent = VianovaAgent(phone)
        reply1, reply2 = agent.process_message(text, key.get('id'))
        
        print(f\"🤖 Réponses: '{reply1[:50]}...' | '{reply2[:50] if reply2 else ''}'\")
        
        if reply1:
            messages = [r for r in [reply1, reply2] if r]
            result = send_conversation_messages(phone, messages)
            print(f\"📤 Résultat: {'✅' if result['success'] else '❌'}\")
            return jsonify({'status': 'success'})
        
        return jsonify({'status': 'no_reply'})
    except Exception as e:
        print(f\"💥 ERREUR: {e}\")
        import traceback
        traceback.print_exc()
        return jsonify({'status': 'error'}), 500

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'healthy', 'port': 8080})

print('='*60)
print('🚀 Serveur Webhook sur PORT 8080')
print('URL: http://187.124.33.83:8080/webhook/whatsapp')
print('='*60)
app.run(host='0.0.0.0', port=8080, debug=False)
" &
sleep 2
curl -s http://localhost:8080/health