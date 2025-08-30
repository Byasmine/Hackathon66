#!/usr/bin/env python3
"""
Reworked Helpdesk AI Agent Support Backend
Two simple routes:
1. POST /api/generate-email - Generate email content for ticket
2. POST /api/send-email - Send email via SMTP
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import pandas as pd
import json
import os
import re
import openai
from datetime import datetime
import uuid
from typing import Dict, List, Optional, Tuple
import logging
from dotenv import load_dotenv
import gspread
from google.oauth2.service_account import Credentials
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import ssl

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)
CORS(app, resources={
    r"/api/*": {
        "origins": ["http://localhost:3000", "http://127.0.0.1:3000"],
        "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization"]
    }
})

# Configure OpenAI
openai.api_key = os.getenv('OPENAI_API_KEY')

# Email configuration
SMTP_CONFIG = {
    'server': os.getenv('SMTP_SERVER', 'email-smtp.eu-north-1.amazonaws.com'),
    'port': int(os.getenv('SMTP_PORT', 465)),
    'tls': os.getenv('SMTP_TLS', 'True').lower() == 'true',
    'user': os.getenv('EMAIL_USER', 'AKIAU6VTTICXXAGUXAM4'),
    'password': os.getenv('EMAIL_PASSWORD', 'BMPmvXyjtfwiyoYr+T+n3l86XbwoS+JWsJ+HKidT4ITp'),
    'from_email': os.getenv('EMAIL_FROM', 'hackathon@kaifact.ai'),
    'supervisor_email': os.getenv('SUPERVISOR_EMAIL', 'yesmineboukhlal@gmail.com')
}

class GoogleSheetsManager:
    """Manages Google Sheets operations for data retrieval"""
    
    def __init__(self):
        self.client = None
        self.sheet_key = os.getenv('GOOGLE_SHEETS_KEY', '1NU0UPK6JMxzlPlnFPm_lD1vBb4zz0sJjJERmertzMGw')
        self._authenticate()
    
    def _authenticate(self):
        """Authenticate with Google Sheets API using service account"""
        try:
            if os.path.exists('service_account.json'):
                scope = ['https://spreadsheets.google.com/feeds',
                        'https://www.googleapis.com/auth/drive']
                
                creds = Credentials.from_service_account_file('service_account.json', scopes=scope)
                self.client = gspread.authorize(creds)
                logger.info("Google Sheets authenticated with service account")
                return True
            
            elif os.path.exists('credentials.json'):
                self.client = gspread.service_account(filename='credentials.json')
                logger.info("Google Sheets authenticated with credentials.json")
                return True
            
            else:
                logger.warning("No Google Sheets credentials found")
                return False
                
        except Exception as e:
            logger.error(f"Google Sheets authentication failed: {e}")
            return False
    
    def get_sheet_data(self):
        """Get data from Google Sheets"""
        if not self.client:
            return None, None
        
        try:
            sheet = self.client.open_by_key(self.sheet_key)
            logger.info(f"Spreadsheet opened successfully: {sheet.title}")
            
            tickets_worksheet = sheet.get_worksheet(0)
            tickets_data = tickets_worksheet.get_all_values()
            
            try:
                interactions_worksheet = sheet.get_worksheet(1)
                interactions_data = interactions_worksheet.get_all_values()
            except:
                interactions_data = None
                logger.warning("No interactions sheet found")
            
            logger.info(f"Retrieved {len(tickets_data)} ticket rows")
            return tickets_data, interactions_data
            
        except Exception as e:
            logger.error(f"Error reading Google Sheets data: {e}")
            return None, None


class EmailSender:
    """Handles actual email sending via SMTP"""
    
    def __init__(self, smtp_config):
        self.smtp_config = smtp_config
    
    def send_email(self, to_email: str, subject: str, body: str) -> Dict:
        """Send email via SMTP"""
        try:
            # Create message
            msg = MIMEMultipart()
            msg['From'] = self.smtp_config['from_email']
            msg['To'] = to_email
            msg['Subject'] = subject
            
            # Add body to email
            msg.attach(MIMEText(body, 'plain', 'utf-8'))
            
            # Create SMTP session
            if self.smtp_config['tls']:
                # Use SSL/TLS
                context = ssl.create_default_context()
                server = smtplib.SMTP_SSL(self.smtp_config['server'], self.smtp_config['port'], context=context)
            else:
                # Use STARTTLS
                server = smtplib.SMTP(self.smtp_config['server'], self.smtp_config['port'])
                server.starttls()
            
            # Login and send
            server.login(self.smtp_config['user'], self.smtp_config['password'])
            text = msg.as_string()
            server.sendmail(self.smtp_config['from_email'], to_email, text)
            server.quit()
            
            logger.info(f"Email sent successfully to {to_email}")
            
            return {
                'success': True,
                'message': 'Email sent successfully',
                'sent_to': to_email,
                'sent_at': datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error sending email: {e}")
            return {
                'success': False,
                'error': f'Failed to send email: {str(e)}'
            }


class HelpdeskProcessor:
    """Main processor for helpdesk tickets and email generation"""
    
    def __init__(self):
        self.tickets_df = None
        self.data_source = "unknown"
        self.sheets_manager = GoogleSheetsManager()
        self.email_sender = EmailSender(SMTP_CONFIG)
        
        # Email templates
        self.templates = {
            'urgent_acknowledgment': {
                'subject': 'URGENT - Accusé de réception - Ticket #{ticket_id}',
                'body': '''Bonjour {customer_name},

Nous avons bien reçu votre demande URGENTE concernant : {issue}

Notre équipe {team} prend immédiatement en charge votre demande avec la plus haute priorité.

{gpt_content}

Nous vous tiendrons informé de l'avancement dans les plus brefs délais.

Cordialement,
L'équipe Support Karizma

Référence: #{ticket_id}'''
            },
            'clarification_request': {
                'subject': 'Demande de clarification - Ticket #{ticket_id}',
                'body': '''Bonjour {customer_name},

Nous avons bien reçu votre demande concernant : {issue}

Notre équipe {team} étudie votre demande fonctionnelle.

{gpt_content}

N'hésitez pas à nous contacter pour toute information complémentaire.

Cordialement,
L'équipe Support Karizma

Référence: #{ticket_id}'''
            },
            'standard_acknowledgment': {
                'subject': 'Accusé de réception - Ticket #{ticket_id}',
                'body': '''Bonjour {customer_name},

Nous avons bien reçu votre demande concernant : {issue}

Notre équipe {team} prend en charge votre demande technique.

{gpt_content}

Nous vous tiendrons informé de l'avancement.

Cordialement,
L'équipe Support Karizma

Référence: #{ticket_id}'''
            }
        }
        
        self.load_data()
    
    def load_data(self):
        """Load data with priority: Google Sheets -> Local file -> No data"""
        
        # Priority 1: Google Sheets
        if self._try_google_sheets():
            self.data_source = "google_sheets"
            return
        
        # Priority 2: Local Excel file
        local_path = 'data/helpdesk_dataset.xlsx'
        if os.path.exists(local_path):
            try:
                logger.info(f"Loading data from local file: {local_path}")
                self.tickets_df = pd.read_excel(local_path, sheet_name='Tickets')
                self._preprocess_data()
                self.data_source = "local_file"
                return
            except Exception as e:
                logger.error(f"Error loading local file: {e}")
        
        # No data available
        logger.error("No data source available")
        self.data_source = "no_data"
        self.tickets_df = None
    
    def _try_google_sheets(self):
        """Try to load from Google Sheets"""
        try:
            if not self.sheets_manager.client:
                return False
            
            tickets_data, _ = self.sheets_manager.get_sheet_data()
            
            if not tickets_data or len(tickets_data) <= 1:
                return False
            
            self.tickets_df = pd.DataFrame(tickets_data[1:], columns=tickets_data[0])
            self._preprocess_data()
            logger.info(f"Loaded {len(self.tickets_df)} tickets from Google Sheets")
            
            return True
            
        except Exception as e:
            logger.error(f"Error loading from Google Sheets: {e}")
            return False
    
    def _preprocess_data(self):
        """Clean and normalize the loaded data"""
        if self.tickets_df is None:
            return
        
        # Convert numeric columns
        numeric_columns = ['ticket_id', 'priority']
        for col in numeric_columns:
            if col in self.tickets_df.columns:
                self.tickets_df[col] = pd.to_numeric(self.tickets_df[col], errors='coerce')
        
        # Clean team names
        if 'team_name' in self.tickets_df.columns:
            self.tickets_df['team_clean'] = self.tickets_df['team_name'].apply(self._clean_team_name)
        else:
            self.tickets_df['team_clean'] = 'DevOps'
        
        # Map priority numbers to text
        if 'priority' in self.tickets_df.columns:
            priority_map = {0: 'Low', 1: 'Medium', 2: 'High', 3: 'Urgent'}
            self.tickets_df['priority_text'] = self.tickets_df['priority'].map(priority_map).fillna('Medium')
        else:
            self.tickets_df['priority_text'] = 'Medium'
        
        # Clean descriptions
        if 'description' in self.tickets_df.columns:
            self.tickets_df['description_clean'] = self.tickets_df['description'].apply(self._clean_description)
        else:
            self.tickets_df['description_clean'] = ''
        
        # Add categorization
        self.tickets_df['is_functional'] = self.tickets_df['description_clean'].apply(self._is_functional_issue)
        self.tickets_df['is_technical'] = self.tickets_df['description_clean'].apply(self._is_technical_issue)
        
        logger.info("Data preprocessing completed")
    
    def _clean_team_name(self, team_name) -> str:
        if pd.isna(team_name) or not team_name:
            return 'DevOps'
        
        team_str = str(team_name)
        if 'Integration 1' in team_str or 'Intégration 1' in team_str:
            return 'Integration 1'
        elif 'Integration 2' in team_str or 'Intégration 2' in team_str:
            return 'Integration 2'
        return 'DevOps'
    
    def _clean_description(self, description) -> str:
        if pd.isna(description) or not description:
            return ''
        return re.sub(r'<[^>]+>', '', str(description)).strip()
    
    def _is_functional_issue(self, description) -> bool:
        if pd.isna(description) or not description:
            return False
        
        functional_keywords = ['dashboard', 'interface', 'menu', 'écran', 'affichage', 'navigation', 'bouton', 'formulaire', 'page', 'visibles']
        description_lower = str(description).lower()
        return any(keyword in description_lower for keyword in functional_keywords)
    
    def _is_technical_issue(self, description) -> bool:
        if pd.isna(description) or not description:
            return False
        
        technical_keywords = ['api', 'webhook', 'synchronisation', 'base de données', 'serveur', 'erreur système', 'crash', 'migration', 'journal', 'e-commerce', 'comptable']
        description_lower = str(description).lower()
        return any(keyword in description_lower for keyword in technical_keywords)
    
    def data_available(self) -> bool:
        """Check if data is available"""
        return self.tickets_df is not None and not self.tickets_df.empty
    
    def get_ticket_by_id(self, ticket_id: int) -> Optional[Dict]:
        """Get a specific ticket by ID"""
        if not self.data_available():
            return None
            
        ticket_row = self.tickets_df[self.tickets_df['ticket_id'] == ticket_id]
        
        if ticket_row.empty:
            return None
        
        ticket_dict = ticket_row.iloc[0].to_dict()
        
        # Convert values for JSON serialization
        for key, value in ticket_dict.items():
            if pd.isna(value):
                ticket_dict[key] = None
            elif isinstance(value, pd.Timestamp):
                ticket_dict[key] = value.isoformat()
        
        return ticket_dict
    
    def determine_response_type(self, ticket: Dict) -> Tuple[str, str]:
        """Determine response type based on ticket analysis"""
        priority = ticket.get('priority_text', 'Medium')
        is_functional = ticket.get('is_functional', False)
        is_technical = ticket.get('is_technical', False)
        
        if priority in ['Urgent', 'High']:
            return 'urgent_acknowledgment', f"Priority is {priority}, requires urgent response"
        elif is_functional:
            return 'clarification_request', 'Functional issue detected, clarification needed'
        elif is_technical and priority in ['Low', 'Medium']:
            return 'standard_acknowledgment', 'Technical non-urgent issue, standard acknowledgment'
        else:
            return 'standard_acknowledgment', 'Standard processing'
    
    def generate_gpt_content(self, ticket: Dict, response_type: str) -> str:
        """Generate contextual content using GPT"""
        try:
            if not openai.api_key or openai.api_key in ['your-openai-api-key-here', None]:
                return self._get_fallback_content(ticket, response_type)
            
            prompt = f"""
Contexte: Je dois répondre à un ticket de support client.

Détails du ticket:
- Client: {ticket.get('customer', '')}
- Sujet: {ticket.get('ticket_subject', '')}
- Priorité: {ticket.get('priority_text', '')}
- Description: {ticket.get('description_clean', '')}
- Équipe: {ticket.get('team_clean', '')}

Type de réponse: {response_type}

Génère un paragraphe professionnel et empathique de 2-3 phrases qui sera inséré dans un email de réponse. 
Le paragraphe doit être personnalisé selon le problème du client et montrer que nous comprenons leur situation.
"""
            
            response = openai.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {
                        "role": "system",
                        "content": "Tu es un assistant de support client professionnel. Génère des réponses empathiques et professionnelles en français."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                max_tokens=200,
                temperature=0.7
            )
            
            return response.choices[0].message.content.strip()
            
        except Exception as e:
            logger.error(f"Error generating GPT content: {e}")
            return self._get_fallback_content(ticket, response_type)
    
    def _get_fallback_content(self, ticket: Dict, response_type: str) -> str:
        """Provide fallback content if GPT fails"""
        fallback_map = {
            'urgent_acknowledgment': "Cette situation requiert notre attention immédiate et nous mobilisons dès maintenant toutes nos ressources pour vous apporter une solution rapide. Notre équipe technique spécialisée va prendre contact avec vous dans les plus brefs délais.",
            'clarification_request': "Afin de vous proposer la solution la plus adaptée à vos besoins, nous souhaiterions obtenir quelques informations complémentaires concernant votre environnement et les circonstances de ce problème. Un membre de notre équipe va vous contacter prochainement.",
            'standard_acknowledgment': "Nous avons assigné votre demande à notre équipe technique qui possède l'expertise nécessaire pour résoudre ce type de problématique. Nous vous tiendrons informé régulièrement de l'avancement de la résolution."
        }
        
        return fallback_map.get(response_type, "Nous prenons en charge votre demande avec toute l'attention qu'elle mérite et vous tiendrons informé de son évolution.")
    
    def generate_email_content(self, ticket_id: int) -> Dict:
        """Generate complete email content for a ticket"""
        try:
            # Check if data is available
            if not self.data_available():
                return {
                    'success': False,
                    'error': 'No data available. Please check your Google Sheets connection or add local data file.'
                }
            
            # Get ticket
            ticket = self.get_ticket_by_id(ticket_id)
            if not ticket:
                return {
                    'success': False,
                    'error': f'Ticket {ticket_id} not found in the dataset'
                }
            
            # Determine response type
            response_type, reasoning = self.determine_response_type(ticket)
            
            # Get template
            template = self.templates.get(response_type)
            
            # Generate GPT content
            gpt_content = self.generate_gpt_content(ticket, response_type)
            
            # Merge everything
            placeholders = {
                'ticket_id': ticket.get('ticket_id', ''),
                'customer_name': ticket.get('customer', ''),
                'issue': ticket.get('ticket_subject', ''),
                'team': ticket.get('team_clean', ''),
                'gpt_content': gpt_content
            }
            
            final_email = {
                'to': ticket.get('customer_email', ''),
                'subject': template['subject'].format(**placeholders),
                'body': template['body'].format(**placeholders)
            }
            
            return {
                'success': True,
                'ticket_id': ticket_id,
                'ticket_info': {
                    'customer': ticket.get('customer'),
                    'subject': ticket.get('ticket_subject'),
                    'priority': ticket.get('priority_text')
                },
                'response_type': response_type,
                'reasoning': reasoning,
                'email': final_email
            }
            
        except Exception as e:
            logger.error(f"Error generating email for ticket {ticket_id}: {e}")
            return {
                'success': False,
                'error': str(e)
            }


# Initialize processor
processor = HelpdeskProcessor()

# =============================================================================
# MAIN ROUTES
# =============================================================================

@app.route('/api/generate-email', methods=['POST'])
def generate_email():
    """
    ROUTE 1: Generate email content for a ticket
    
    Request: {"ticket_id": 30000}
    Response: {
        "success": true,
        "ticket_id": 30000,
        "email": {
            "to": "customer@example.com",
            "subject": "Email subject",
            "body": "Email body content"
        }
    }
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No JSON data provided'}), 400
        
        ticket_id = data.get('ticket_id')
        
        if not ticket_id:
            return jsonify({'success': False, 'error': 'ticket_id is required'}), 400
        
        logger.info(f"Generating email for ticket {ticket_id}")
        
        result = processor.generate_email_content(int(ticket_id))
        
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Error in generate_email: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/send-email', methods=['POST'])
def send_email():
    """
    ROUTE 2: Send email via SMTP
    
    Request: {
        "ticket_id": 30000,
        "to": "customer@example.com",
        "subject": "Email subject", 
        "body": "Email body"
    }
    Response: {
        "success": true,
        "message": "Email sent successfully",
        "sent_to": "customer@example.com"
    }
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No JSON data provided'}), 400
        
        ticket_id = data.get('ticket_id')
        to_email = data.get('to')
        subject = data.get('subject')
        body = data.get('body')
        
        if not all([ticket_id, to_email, subject, body]):
            return jsonify({
                'success': False, 
                'error': 'ticket_id, to, subject, and body are all required'
            }), 400
        
        logger.info(f"Sending email for ticket {ticket_id} to {to_email}")
        
        # Send email via SMTP
        result = processor.email_sender.send_email(to_email, subject, body)
        
        if result['success']:
            result['ticket_id'] = ticket_id
        
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Error in send_email: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# =============================================================================
# UTILITY ENDPOINTS
# =============================================================================

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'OK',
        'timestamp': datetime.now().isoformat(),
        'tickets_loaded': len(processor.tickets_df) if processor.data_available() else 0,
        'data_source': processor.data_source,
        'data_available': processor.data_available(),
        'google_sheets_connected': processor.data_source == "google_sheets",
        'openai_configured': openai.api_key is not None and openai.api_key not in ['your-openai-api-key-here'],
        'smtp_configured': all([SMTP_CONFIG['server'], SMTP_CONFIG['user'], SMTP_CONFIG['password']])
    })

@app.route('/api/tickets', methods=['GET'])
def get_tickets():
    """Get available tickets"""
    try:
        if not processor.data_available():
            return jsonify({
                'success': False, 
                'error': 'No data available. Please check your data sources.',
                'data_source': processor.data_source
            }), 404
        
        limit = request.args.get('limit', 10, type=int)
        tickets = processor.tickets_df.head(limit).to_dict('records')
        
        # Convert timestamps for JSON
        for ticket in tickets:
            for key, value in ticket.items():
                if pd.isna(value):
                    ticket[key] = None
                elif isinstance(value, pd.Timestamp):
                    ticket[key] = value.isoformat()
        
        return jsonify({
            'success': True,
            'tickets': tickets,
            'total': len(processor.tickets_df),
            'data_source': processor.data_source
        })
        
    except Exception as e:
        logger.error(f"Error getting tickets: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/test-smtp', methods=['POST'])
def test_smtp():
    """Test SMTP configuration"""
    try:
        test_email = {
            'to': SMTP_CONFIG['supervisor_email'],
            'subject': 'Test Email from Helpdesk Backend',
            'body': f'This is a test email sent at {datetime.now().isoformat()}\n\nSMTP configuration is working correctly!'
        }
        
        result = processor.email_sender.send_email(
            test_email['to'], 
            test_email['subject'], 
            test_email['body']
        )
        
        return jsonify({
            'success': result['success'],
            'message': result.get('message', 'Test completed'),
            'test_email_sent_to': test_email['to'],
            'smtp_server': SMTP_CONFIG['server'],
            'error': result.get('error')
        })
        
    except Exception as e:
        logger.error(f"Error testing SMTP: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# =============================================================================
# ERROR HANDLERS
# =============================================================================

@app.errorhandler(404)
def not_found(error):
    return jsonify({'success': False, 'error': 'Endpoint not found'}), 404

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"Internal server error: {error}")
    return jsonify({'success': False, 'error': 'Internal server error'}), 500

# =============================================================================
# MAIN APPLICATION STARTUP
# =============================================================================

if __name__ == '__main__':
    print("=" * 60)
    print("HELPDESK AI AGENT SUPPORT BACKEND")
    print("=" * 60)
    
    if processor.data_available():
        print(f"Tickets loaded: {len(processor.tickets_df)}")
        print(f"Data source: {processor.data_source.upper()}")
        
        if processor.data_source == "google_sheets":
            print("Using Google Sheets")
        elif processor.data_source == "local_file":
            print("Using local Excel file")
        
        # Show sample ticket IDs
        if 'ticket_id' in processor.tickets_df.columns:
            sample_ids = processor.tickets_df['ticket_id'].head(5).tolist()
            print(f"Sample Ticket IDs: {sample_ids}")
    else:
        print("NO DATA AVAILABLE")
        print("Setup required:")
        print("1. Add service_account.json for Google Sheets")
        print("2. Or place Excel file as: data/helpdesk_dataset.xlsx")
    
    print(f"OpenAI configured: {'YES' if openai.api_key and openai.api_key not in ['your-openai-api-key-here'] else 'NO'}")
    print(f"SMTP configured: {'YES' if SMTP_CONFIG['user'] != 'AKIAU6VTTICXXAGUXAM4' else 'NO'}")
    print(f"Server starting on: http://0.0.0.0:5000")
    print("=" * 60)
    print("\nMAIN ROUTES:")
    print("1. POST /api/generate-email  - Generate email content")
    print("2. POST /api/send-email      - Send email via SMTP")
    print("\nUTILITY ROUTES:")
    print("   GET  /api/health          - Health check")
    print("   GET  /api/tickets         - Get available tickets")
    print("   POST /api/test-smtp       - Test email sending")
    print("=" * 60)
    
    # Start Flask application
    app.run(
        host='0.0.0.0',
        port=int(os.environ.get('PORT', 5000)),
        debug=os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    )