#!/usr/bin/env python3
"""Exemples d'utilisation de l'API dashboard"""
import requests
import json

API_BASE_URL = "http://localhost:5000/api"

def print_section(title):
    """Affiche une section"""
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}\n")

def example_1_create_lead():
    """Exemple 1: Créer un lead"""
    print_section("EXEMPLE 1: Créer un lead")
    
    lead_data = {
        "phone": "+33612345678",
        "nom": "Dupont",
        "prenom": "Jean",
        "ville": "Paris",
        "typing": "residence",
        "budget": "500000",
        "state": "initial"
    }
    
    print(f"Données du lead à créer:")
    print(json.dumps(lead_data, indent=2, ensure_ascii=False))
    
    print(f"\n📤 POST {API_BASE_URL}/leads")
    
    try:
        response = requests.post(f"{API_BASE_URL}/leads", json=lead_data)
        print(f"Status: {response.status_code}")
        print(f"Réponse: {json.dumps(response.json(), indent=2, ensure_ascii=False)}")
    except Exception as e:
        print(f"❌ Erreur: {e}")

def example_2_get_leads():
    """Exemple 2: Récupérer tous les leads"""
    print_section("EXEMPLE 2: Récupérer tous les leads")
    
    print(f"📥 GET {API_BASE_URL}/leads")
    
    try:
        response = requests.get(f"{API_BASE_URL}/leads")
        print(f"Status: {response.status_code}")
        data = response.json()
        print(f"Total leads: {data['count']}")
        
        if data['leads']:
            print(f"\n📋 Leads:")
            for lead in data['leads']:
                print(f"  - {lead['prenom']} {lead['nom']} ({lead['phone']})")
                print(f"    État: {lead['state']}")
                print(f"    Ville: {lead['ville']}")
    except Exception as e:
        print(f"❌ Erreur: {e}")

def example_3_get_single_lead():
    """Exemple 3: Récupérer un lead spécifique"""
    print_section("EXEMPLE 3: Récupérer un lead spécifique")
    
    phone = "+33612345678"
    print(f"📥 GET {API_BASE_URL}/leads/{phone}")
    
    print(f"(Via dashboard_api, chercher le lead dans la réponse GET /leads)")

def example_4_update_lead():
    """Exemple 4: Mettre à jour un lead"""
    print_section("EXEMPLE 4: Mettre à jour un lead")
    
    phone = "+33612345678"
    updates = {
        "ville": "Marseille",
        "budget": "600000",
        "state": "en_cours"
    }
    
    print(f"Mises à jour:")
    print(json.dumps(updates, indent=2, ensure_ascii=False))
    
    print(f"\n✏️  PUT {API_BASE_URL}/leads/{phone}")
    
    try:
        response = requests.put(f"{API_BASE_URL}/leads/{phone}", json=updates)
        print(f"Status: {response.status_code}")
        print(f"Réponse: {json.dumps(response.json(), indent=2, ensure_ascii=False)}")
    except Exception as e:
        print(f"❌ Erreur: {e}")

def example_5_change_state():
    """Exemple 5: Changer l'état d'un lead"""
    print_section("EXEMPLE 5: Changer l'état d'un lead")
    
    phone = "+33612345678"
    state_data = {"state": "rdv_propose"}
    
    print(f"Nouvel état: {state_data['state']}")
    
    print(f"\n🔄 POST {API_BASE_URL}/leads/{phone}/state")
    
    try:
        response = requests.post(f"{API_BASE_URL}/leads/{phone}/state", json=state_data)
        print(f"Status: {response.status_code}")
        print(f"Réponse: {json.dumps(response.json(), indent=2, ensure_ascii=False)}")
    except Exception as e:
        print(f"❌ Erreur: {e}")

def example_6_toggle_ai():
    """Exemple 6: Toggle l'IA pour un lead"""
    print_section("EXEMPLE 6: Activer/désactiver l'IA")
    
    phone = "+33612345678"
    
    print(f"🤖 POST {API_BASE_URL}/leads/{phone}/toggle-ai")
    
    try:
        response = requests.post(f"{API_BASE_URL}/leads/{phone}/toggle-ai")
        print(f"Status: {response.status_code}")
        print(f"Réponse: {json.dumps(response.json(), indent=2, ensure_ascii=False)}")
    except Exception as e:
        print(f"❌ Erreur: {e}")

def example_7_send_message():
    """Exemple 7: Envoyer un message manuel"""
    print_section("EXEMPLE 7: Envoyer un message manuel")
    
    phone = "+33612345678"
    message_data = {
        "message": "Bonjour, comment allez-vous ?"
    }
    
    print(f"Message à envoyer: {message_data['message']}")
    
    print(f"\n📤 POST {API_BASE_URL}/leads/{phone}/message")
    
    try:
        response = requests.post(f"{API_BASE_URL}/leads/{phone}/message", json=message_data)
        print(f"Status: {response.status_code}")
        print(f"Réponse: {json.dumps(response.json(), indent=2, ensure_ascii=False)}")
    except Exception as e:
        print(f"❌ Erreur: {e}")

def example_8_get_messages():
    """Exemple 8: Récupérer les messages d'un lead"""
    print_section("EXEMPLE 8: Récupérer l'historique des messages")
    
    phone = "+33612345678"
    
    print(f"💬 GET {API_BASE_URL}/leads/{phone}/messages")
    
    try:
        response = requests.get(f"{API_BASE_URL}/leads/{phone}/messages")
        print(f"Status: {response.status_code}")
        data = response.json()
        
        if data['messages']:
            print(f"\n📜 Messages:")
            for msg in data['messages']:
                print(f"  [{msg['role']}] {msg['content']}")
                print(f"    À: {msg['timestamp']}")
        else:
            print("Aucun message")
    except Exception as e:
        print(f"❌ Erreur: {e}")

def example_9_get_stats():
    """Exemple 9: Récupérer les statistiques"""
    print_section("EXEMPLE 9: Récupérer les statistiques")
    
    print(f"📊 GET {API_BASE_URL}/stats")
    
    try:
        response = requests.get(f"{API_BASE_URL}/stats")
        print(f"Status: {response.status_code}")
        print(f"Réponse:")
        print(json.dumps(response.json(), indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"❌ Erreur: {e}")

def example_10_check_relances():
    """Exemple 10: Vérifier les relances"""
    print_section("EXEMPLE 10: Vérifier et envoyer les relances")
    
    print(f"⏰ POST {API_BASE_URL}/relance/check")
    
    try:
        response = requests.post(f"{API_BASE_URL}/relance/check")
        print(f"Status: {response.status_code}")
        data = response.json()
        
        if data['relanced']:
            print(f"\n📞 {len(data['relanced'])} relances envoyées:")
            for phone in data['relanced']:
                print(f"  - {phone}")
        else:
            print("Aucune relance nécessaire")
    except Exception as e:
        print(f"❌ Erreur: {e}")

def example_11_delete_lead():
    """Exemple 11: Supprimer un lead"""
    print_section("EXEMPLE 11: Supprimer un lead")
    
    phone = "+33612345678"
    
    print(f"🗑️  DELETE {API_BASE_URL}/leads/{phone}")
    
    try:
        response = requests.delete(f"{API_BASE_URL}/leads/{phone}")
        print(f"Status: {response.status_code}")
        print(f"Réponse: {json.dumps(response.json(), indent=2, ensure_ascii=False)}")
    except Exception as e:
        print(f"❌ Erreur: {e}")

def example_12_health_check():
    """Exemple 12: Vérifier la santé de l'API"""
    print_section("EXEMPLE 12: Health Check")
    
    print(f"🏥 GET {API_BASE_URL}/health")
    
    try:
        response = requests.get(f"{API_BASE_URL}/health")
        print(f"Status: {response.status_code}")
        print(f"Réponse: {json.dumps(response.json(), indent=2, ensure_ascii=False)}")
    except Exception as e:
        print(f"❌ Erreur: {e}")

if __name__ == '__main__':
    print("\n" + "="*60)
    print("  📚 EXEMPLES D'UTILISATION API DASHBOARD")
    print("="*60)
    print("\nℹ️  Assurez-vous que l'API est démarrée: python3 dashboard_api.py")
    
    # Exécuter les exemples
    try:
        example_12_health_check()
        example_1_create_lead()
        example_2_get_leads()
        example_4_update_lead()
        example_5_change_state()
        example_6_toggle_ai()
        example_8_get_messages()
        example_9_get_stats()
        example_10_check_relances()
        example_11_delete_lead()
        
    except KeyboardInterrupt:
        print("\n\n⏹️  Arrêt...")
    except Exception as e:
        print(f"\n❌ Erreur: {e}")
    
    print("\n" + "="*60)
    print("  ✅ Exemples terminés")
    print("="*60 + "\n")
