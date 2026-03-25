"""
VIANOVA Leads Dashboard - Backend Example
Flask API implementation for the leads management dashboard

Installation:
    pip install flask flask-cors

Run:
    python backend_example.py

This is a basic example with in-memory storage.
For production, use a real database (PostgreSQL, MongoDB, etc.)
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
from datetime import datetime
from typing import List, Dict, Any
import json
import os

app = Flask(__name__)
CORS(app)

# ============= IN-MEMORY STORAGE (Replace with DB) =============
# For production, use SQLAlchemy + PostgreSQL/MySQL
leads_db = []
templates_db = {
    'initial': 'Bonjour {prenom},\n\nVous recherchez une {ville}? Nous avons des biens correspondant à votre budget de {budget}.\n\nCordialement',
    'relance_24h': 'Bonjour {prenom},\n\nVous avez reçu notre message hier. Vous êtes intéressé?',
    'relance_72h': 'Bonjour {prenom},\n\nDernier appel! Nous avons une belle opportunité à {ville}.'
}
campaigns_db = []
lead_counter = 0

# ============= LEADS ENDPOINTS =============

@app.route('/api/leads', methods=['GET'])
def get_leads():
    """Get all leads"""
    try:
        return jsonify({
            'success': True,
            'leads': leads_db
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/leads', methods=['POST'])
def create_lead():
    """Create a new lead"""
    try:
        global lead_counter
        
        data = request.json
        
        # Validation
        if not data.get('nom') or not data.get('prenom') or not data.get('telephone'):
            return jsonify({
                'success': False,
                'message': 'nom, prenom, and telephone are required'
            }), 400
        
        lead = {
            'id': lead_counter,
            'nom': data.get('nom', '').strip(),
            'prenom': data.get('prenom', '').strip(),
            'telephone': data.get('telephone', '').strip(),
            'ville': data.get('ville', '').strip(),
            'typologie': data.get('typologie', ''),
            'budget': data.get('budget', '').strip(),
            'date_dernier_contact': data.get('date_dernier_contact', ''),
            'date_envoi': data.get('date_envoi', ''),
            'etat': data.get('etat', 'initial'),
            'created_at': datetime.now().isoformat()
        }
        
        leads_db.append(lead)
        lead_counter += 1
        
        return jsonify({
            'success': True,
            'message': 'Lead created',
            'lead': lead
        }), 201
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/leads/import', methods=['POST'])
def import_leads():
    """Import multiple leads from CSV"""
    try:
        global lead_counter
        
        data = request.json
        leads_to_import = data.get('leads', [])
        
        if not leads_to_import:
            return jsonify({
                'success': False,
                'message': 'No leads provided'
            }), 400
        
        imported_count = 0
        
        for lead_data in leads_to_import:
            # Validation
            if not lead_data.get('nom') or not lead_data.get('prenom') or not lead_data.get('telephone'):
                continue
            
            lead = {
                'id': lead_counter,
                'nom': lead_data.get('nom', '').strip(),
                'prenom': lead_data.get('prenom', '').strip(),
                'telephone': lead_data.get('telephone', '').strip(),
                'ville': lead_data.get('ville', '').strip(),
                'typologie': lead_data.get('typologie', ''),
                'budget': lead_data.get('budget', '').strip(),
                'date_dernier_contact': lead_data.get('date_dernier_contact', ''),
                'date_envoi': lead_data.get('date_envoi', ''),
                'etat': lead_data.get('etat', 'initial'),
                'created_at': datetime.now().isoformat()
            }
            
            leads_db.append(lead)
            lead_counter += 1
            imported_count += 1
        
        return jsonify({
            'success': True,
            'message': f'{imported_count} leads imported',
            'count': imported_count
        }), 201
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/leads/<int:lead_id>', methods=['GET'])
def get_lead(lead_id):
    """Get a specific lead"""
    try:
        lead = next((l for l in leads_db if l['id'] == lead_id), None)
        
        if not lead:
            return jsonify({
                'success': False,
                'message': 'Lead not found'
            }), 404
        
        return jsonify({
            'success': True,
            'lead': lead
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/leads/<int:lead_id>', methods=['PUT'])
def update_lead(lead_id):
    """Update a lead"""
    try:
        lead = next((l for l in leads_db if l['id'] == lead_id), None)
        
        if not lead:
            return jsonify({
                'success': False,
                'message': 'Lead not found'
            }), 404
        
        data = request.json
        
        # Update fields
        if 'nom' in data:
            lead['nom'] = data['nom'].strip()
        if 'prenom' in data:
            lead['prenom'] = data['prenom'].strip()
        if 'telephone' in data:
            lead['telephone'] = data['telephone'].strip()
        if 'ville' in data:
            lead['ville'] = data['ville'].strip()
        if 'typologie' in data:
            lead['typologie'] = data['typologie']
        if 'budget' in data:
            lead['budget'] = data['budget'].strip()
        if 'date_dernier_contact' in data:
            lead['date_dernier_contact'] = data['date_dernier_contact']
        if 'date_envoi' in data:
            lead['date_envoi'] = data['date_envoi']
        if 'etat' in data:
            lead['etat'] = data['etat']
        
        lead['updated_at'] = datetime.now().isoformat()
        
        return jsonify({
            'success': True,
            'message': 'Lead updated',
            'lead': lead
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/leads/<int:lead_id>', methods=['DELETE'])
def delete_lead(lead_id):
    """Delete a lead"""
    try:
        global leads_db
        
        lead = next((l for l in leads_db if l['id'] == lead_id), None)
        
        if not lead:
            return jsonify({
                'success': False,
                'message': 'Lead not found'
            }), 404
        
        leads_db = [l for l in leads_db if l['id'] != lead_id]
        
        return jsonify({
            'success': True,
            'message': 'Lead deleted'
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


# ============= CAMPAIGNS ENDPOINTS =============

@app.route('/api/campaign/launch', methods=['POST'])
def launch_campaign():
    """Launch a campaign"""
    try:
        data = request.json
        
        message = data.get('message', '').strip()
        batch_size = min(int(data.get('batch_size', 10)), 100)  # Max 100 per batch
        dry_run = data.get('dry_run', False)
        leads_to_send = data.get('leads', [])
        
        if not message:
            return jsonify({
                'success': False,
                'message': 'Message is required'
            }), 400
        
        if not leads_to_send:
            return jsonify({
                'success': False,
                'message': 'No leads provided'
            }), 400
        
        # Limit to batch_size
        leads_to_send = leads_to_send[:batch_size]
        
        # Build campaign record
        campaign = {
            'id': len(campaigns_db),
            'message': message,
            'batch_size': len(leads_to_send),
            'dry_run': dry_run,
            'leads_count': len(leads_to_send),
            'status': 'pending',
            'created_at': datetime.now().isoformat()
        }
        
        # In production, this would send actual messages via WhatsApp API, etc.
        if not dry_run:
            print(f"[CAMPAIGN] Sending {len(leads_to_send)} messages...")
            for lead in leads_to_send:
                # Example: send_whatsapp_message(lead['telephone'], message)
                print(f"  → {lead['prenom']} {lead['nom']} ({lead['telephone']})")
            
            campaign['status'] = 'sent'
        else:
            campaign['status'] = 'test_completed'
        
        campaigns_db.append(campaign)
        
        return jsonify({
            'success': True,
            'message': f'Campaign {"tested" if dry_run else "launched"} successfully',
            'campaign': campaign
        }), 201
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


# ============= TEMPLATES ENDPOINTS =============

@app.route('/api/templates/<template_key>', methods=['GET'])
def get_template(template_key):
    """Get a template"""
    try:
        if template_key not in templates_db:
            return jsonify({
                'success': False,
                'message': f'Template {template_key} not found'
            }), 404
        
        return jsonify({
            'success': True,
            'template': template_key,
            'content': templates_db[template_key]
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/templates/<template_key>/preview', methods=['GET'])
def preview_template(template_key):
    """Get template preview"""
    try:
        if template_key not in templates_db:
            return jsonify({
                'success': False,
                'message': f'Template {template_key} not found'
            }), 404
        
        return jsonify({
            'success': True,
            'template': template_key,
            'preview': templates_db[template_key]
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/templates/<template_key>', methods=['POST'])
def save_template(template_key):
    """Save a template"""
    try:
        data = request.json
        content = data.get('content', '').strip()
        
        if not content:
            return jsonify({
                'success': False,
                'message': 'Content is required'
            }), 400
        
        templates_db[template_key] = content
        
        return jsonify({
            'success': True,
            'message': f'Template {template_key} saved',
            'template': template_key
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


# ============= STATISTICS ENDPOINTS =============

@app.route('/api/stats', methods=['GET'])
def get_stats():
    """Get statistics"""
    try:
        # Count leads by state
        total_leads = len(leads_db)
        en_cours = len([l for l in leads_db if l.get('etat') == 'en_cours'])
        rdv_proposed = len([l for l in leads_db if l.get('etat') == 'rdv_propose'])
        rdv_confirmed = len([l for l in leads_db if l.get('etat') == 'rdv_confirme'])
        closed = len([l for l in leads_db if l.get('etat') == 'clos'])
        
        # Campaign stats
        total_campaigns = len(campaigns_db)
        sent_campaigns = len([c for c in campaigns_db if c.get('status') == 'sent'])
        total_messages = sum([c.get('batch_size', 0) for c in campaigns_db if c.get('status') == 'sent'])
        
        stats = {
            'total_leads': total_leads,
            'en_cours': en_cours,
            'rdv_proposed': rdv_proposed,
            'rdv_confirmed': rdv_confirmed,
            'closed': closed,
            'total_campaigns': total_campaigns,
            'messages_sent': total_messages,
            'rdv_total': rdv_proposed + rdv_confirmed,
            'closed_total': closed
        }
        
        return jsonify({
            'success': True,
            'stats': stats
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


# ============= HEALTH CHECK =============

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'ok',
        'leads': len(leads_db),
        'campaigns': len(campaigns_db)
    })


# ============= ERROR HANDLERS =============

@app.errorhandler(404)
def not_found(error):
    return jsonify({'success': False, 'message': 'Endpoint not found'}), 404


@app.errorhandler(500)
def internal_error(error):
    return jsonify({'success': False, 'message': 'Internal server error'}), 500


# ============= MAIN =============

if __name__ == '__main__':
    print("🚀 VIANOVA Leads Dashboard API")
    print("📍 Running on http://localhost:5000")
    print("💡 Visit http://localhost:5000/api/health to test")
    
    # Load example data
    print("\n📊 Loading example data...")
    example_leads = [
        {
            'nom': 'Dupont',
            'prenom': 'Jean',
            'telephone': '+33612345678',
            'ville': 'Paris',
            'typologie': 'T2',
            'budget': '250000€',
            'date_dernier_contact': '2024-03-10',
            'date_envoi': '2024-03-10',
            'etat': 'en_cours'
        },
        {
            'nom': 'Martin',
            'prenom': 'Marie',
            'telephone': '+33623456789',
            'ville': 'Lyon',
            'typologie': 'T3',
            'budget': '350000€',
            'date_dernier_contact': '2024-03-12',
            'date_envoi': '2024-03-12',
            'etat': 'rdv_propose'
        }
    ]
    
    for lead_data in example_leads:
        lead = {
            'id': lead_counter,
            'created_at': datetime.now().isoformat(),
            **lead_data
        }
        leads_db.append(lead)
        lead_counter += 1
    
    print(f"✅ Loaded {len(leads_db)} example leads")
    
    # Start Flask app
    app.run(debug=True, host='localhost', port=5000)
