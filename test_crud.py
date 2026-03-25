#!/usr/bin/env python3
"""Tests pour les endpoints CRUD des leads"""
import json
import logging
import os
from datetime import datetime
from redis_client import RedisClient
from leads_manager import LeadsManager

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("test_crud")

def test_crud():
    """Test des opérations CRUD"""
    logger.info("=" * 60)
    logger.info("🧪 TESTS CRUD - LeadsManager")
    logger.info("=" * 60)
    
    # Configuration test
    redis_url = "redis://localhost:6379"
    json_file = "test_leads.json"
    
    try:
        # Initialiser Redis et LeadsManager
        redis_client = RedisClient(redis_url)
        leads_manager = LeadsManager(redis_client, json_file)
        
        # Nettoyer les données précédentes
        for lead in leads_manager.list_leads():
            leads_manager.delete_lead(lead['phone'])
        
        logger.info("\n✅ Clients initialisés")
        
        # ==================== TEST CREATE ====================
        logger.info("\n🔨 TEST CREATE")
        
        lead1_data = {
            'phone': '+33612345678',
            'nom': 'Dupont',
            'prenom': 'Jean',
            'ville': 'Paris',
            'typing': 'residence',
            'budget': '500000',
            'state': 'initial',
            'ai_enabled': True
        }
        
        result = leads_manager.add_lead(lead1_data)
        assert result, "❌ Erreur ajout lead 1"
        logger.info("✅ Lead 1 ajouté")
        
        lead2_data = {
            'phone': '+33687654321',
            'nom': 'Martin',
            'prenom': 'Marie',
            'ville': 'Lyon',
            'typing': 'invest',
            'budget': '200000',
            'state': 'initial'
        }
        
        result = leads_manager.add_lead(lead2_data)
        assert result, "❌ Erreur ajout lead 2"
        logger.info("✅ Lead 2 ajouté")
        
        # ==================== TEST READ ====================
        logger.info("\n📖 TEST READ")
        
        lead = leads_manager.get_lead('+33612345678')
        assert lead is not None, "❌ Lead non trouvé"
        assert lead['nom'] == 'Dupont', "❌ Nom incorrect"
        logger.info(f"✅ Lead récupéré: {lead['prenom']} {lead['nom']}")
        
        # ==================== TEST LIST ====================
        logger.info("\n📋 TEST LIST")
        
        all_leads = leads_manager.list_leads()
        assert len(all_leads) == 2, f"❌ Nombre de leads incorrect: {len(all_leads)}"
        logger.info(f"✅ {len(all_leads)} leads listés")
        
        for l in all_leads:
            logger.info(f"   - {l['prenom']} {l['nom']} ({l['phone']})")
        
        # ==================== TEST UPDATE ====================
        logger.info("\n✏️  TEST UPDATE")
        
        result = leads_manager.update_lead('+33612345678', {
            'ville': 'Marseille',
            'budget': '600000',
            'state': 'en_cours'
        })
        assert result, "❌ Erreur mise à jour"
        
        updated_lead = leads_manager.get_lead('+33612345678')
        assert updated_lead['ville'] == 'Marseille', "❌ Ville non mise à jour"
        assert updated_lead['state'] == 'en_cours', "❌ État non mis à jour"
        logger.info("✅ Lead mis à jour")
        
        # ==================== TEST STATE ====================
        logger.info("\n🔄 TEST STATE")
        
        state = leads_manager.get_state('+33612345678')
        assert state == 'en_cours', "❌ État incorrect"
        logger.info(f"✅ État récupéré: {state}")
        
        result = leads_manager.set_state('+33612345678', 'rdv_propose')
        assert result, "❌ Erreur mise à jour état"
        
        state = leads_manager.get_state('+33612345678')
        assert state == 'rdv_propose', "❌ État non mis à jour"
        logger.info(f"✅ État mis à jour: {state}")
        
        # ==================== TEST TOGGLE AI ====================
        logger.info("\n🤖 TEST TOGGLE AI")
        
        new_state = leads_manager.toggle_ai('+33612345678')
        assert new_state == False, "❌ AI toggle incorrect"
        logger.info(f"✅ IA désactivée: {new_state}")
        
        new_state = leads_manager.toggle_ai('+33612345678')
        assert new_state == True, "❌ AI toggle incorrect"
        logger.info(f"✅ IA réactivée: {new_state}")
        
        # ==================== TEST FILTER ====================
        logger.info("\n🔍 TEST FILTER")
        
        en_cours_leads = leads_manager.list_leads(filter_state='rdv_propose')
        assert len(en_cours_leads) >= 1, "❌ Filtre non fonctionnel"
        logger.info(f"✅ Filtrage: {len(en_cours_leads)} lead(s) en état 'rdv_propose'")
        
        # ==================== TEST JSON PERSISTENCE ====================
        logger.info("\n💾 TEST JSON PERSISTENCE")
        
        # Vérifier que le fichier JSON a été créé
        assert os.path.exists(json_file), "❌ Fichier JSON non créé"
        logger.info(f"✅ Fichier JSON créé: {json_file}")
        
        # Vérifier le contenu du JSON
        with open(json_file, 'r') as f:
            json_data = json.load(f)
        
        assert 'leads' in json_data, "❌ Format JSON incorrect"
        assert len(json_data['leads']) == 2, "❌ Nombre de leads dans JSON incorrect"
        logger.info(f"✅ JSON contient {len(json_data['leads'])} leads")
        
        # ==================== TEST STATS ====================
        logger.info("\n📊 TEST STATS")
        
        stats = leads_manager.get_stats()
        assert stats['total'] == 2, "❌ Stats total incorrect"
        assert 'by_state' in stats, "❌ Stats by_state manquant"
        logger.info(f"✅ Stats: {stats['total']} leads")
        logger.info(f"   Par état: {stats['by_state']}")
        
        # ==================== TEST DELETE ====================
        logger.info("\n🗑️  TEST DELETE")
        
        result = leads_manager.delete_lead('+33687654321')
        assert result, "❌ Erreur suppression"
        
        all_leads = leads_manager.list_leads()
        assert len(all_leads) == 1, "❌ Lead non supprimé"
        logger.info("✅ Lead supprimé")
        
        # Vérifier que le JSON a été mis à jour
        with open(json_file, 'r') as f:
            json_data = json.load(f)
        
        assert len(json_data['leads']) == 1, "❌ JSON non mis à jour après suppression"
        logger.info("✅ JSON synchronisé après suppression")
        
        # ==================== TEST IMPORT/EXPORT ====================
        logger.info("\n📤 TEST IMPORT/EXPORT")
        
        export_file = "test_export.json"
        result = leads_manager.export_to_json_file(export_file)
        assert result, "❌ Erreur export"
        assert os.path.exists(export_file), "❌ Fichier export non créé"
        logger.info(f"✅ Export réussi: {export_file}")
        
        # Import dans un nouveau LeadsManager
        leads_manager2 = LeadsManager(RedisClient(redis_url), "test_leads2.json")
        for lead in leads_manager2.list_leads():
            leads_manager2.delete_lead(lead['phone'])
        
        result = leads_manager2.import_from_json_file(export_file)
        assert result, "❌ Erreur import"
        
        imported_leads = leads_manager2.list_leads()
        assert len(imported_leads) == 1, "❌ Import incomplet"
        logger.info(f"✅ Import réussi: {len(imported_leads)} lead(s)")
        
        # ==================== RÉSUMÉ ====================
        logger.info("\n" + "=" * 60)
        logger.info("✅ TOUS LES TESTS RÉUSSIS!")
        logger.info("=" * 60)
        
        # Cleanup
        os.remove(json_file)
        os.remove(export_file)
        os.remove("test_leads2.json")
        
        return True
    
    except AssertionError as e:
        logger.error(f"❌ Test échoué: {e}")
        return False
    except Exception as e:
        logger.error(f"❌ Erreur: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    import sys
    success = test_crud()
    sys.exit(0 if success else 1)
