#!/usr/bin/env python3
"""Script de test - Envoie un message WhatsApp de test"""
import sys
sys.path.insert(0, '/data/.openclaw/workspace/vianova-agent/.local/lib/python3.13/site-packages')

from tools.evolution import send_message, check_connection
from agent_ia import VianovaAgent

PHONE_TEST = "33630102782"

def main():
    print("=" * 60)
    print("🧪 TEST ENVOI WHATSAPP")
    print("=" * 60)
    
    # 1. Vérifier connexion Evolution
    print("\n1. Vérification connexion Evolution API...")
    if not check_connection():
        print("❌ Evolution API non connectée!")
        print("   Vérifie que ton instance est bien démarrée sur:")
        print("   https://evolution.monagentia.cloud/manager")
        return
    print("✅ Evolution API connectée")
    
    # 2. Préparer message de test
    print(f"\n2. Préparation message pour +{PHONE_TEST}...")
    
    # Message varié naturel
    import random
    messages = [
        "Bonjour ! C'est Daniel de Vianova. Je reprends contact suite à votre recherche immobilière. Toujours intéressé par l'achat dans le neuf ?",
        "Bonjour, Daniel de Vianova ici. Je me permets de revenir vers vous concernant votre projet. Toujours en recherche ?",
        "Bonjour 👋 C'est Daniel de Vianova. Petite relance sur votre projet immobilier. Vous avez avancé de votre côté ?"
    ]
    message = random.choice(messages)
    
    print(f"📝 Message choisi: {message[:50]}...")
    
    # 3. Envoyer
    print(f"\n3. Envoi en cours...")
    result = send_message(PHONE_TEST, message, delay=(2, 5))
    
    if result["success"]:
        print(f"✅ Message envoyé avec succès!")
        print(f"   Message ID: {result.get('messageId', 'N/A')}")
        
        # Sauvegarder dans mémoire
        agent = VianovaAgent(PHONE_TEST)
        agent.set_initial_message_sent(True)
        agent.memory.add_message("assistant", message, result.get("messageId"))
        print(f"💾 Sauvegardé dans conversation_memory")
        
        print(f"\n📱 Vérifie ton WhatsApp sur le numéro +{PHONE_TEST}")
        
    else:
        print(f"❌ Échec de l'envoi")
        print(f"   Erreur: {result.get('error', 'Inconnue')}")
        print(f"\n💡 Conseil: Vérifie que le numéro est au format 336...")

if __name__ == "__main__":
    main()