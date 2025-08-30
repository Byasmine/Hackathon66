#!/usr/bin/env python3
"""
Helpdesk AI Agent Support Backend
Complete Flask implementation with Google Sheets integration using gspread.
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

class GoogleSheetsManager:
    """Manages Google Sheets operations for data retrieval"""
    
    def __init__(self):
        self.client = None
        self.sheet_key = os.getenv('GOOGLE_SHEETS_KEY', '1NU0UPK6JMxzlPlnFPm_lD1vBb4zz0sJjJERmertzMGw')
        self._authenticate()
    
    def _authenticate(self):
        """Authenticate with Google Sheets API using service account"""
        try:
            # Try service account authentication first
            if os.path.exists('service_account.json'):
                scope = ['https://spreadsheets.google.com/feeds',
                        'https://www.googleapis.com/auth/drive']
                
                creds = Credentials.from_service_account_file('service_account.json', scopes=scope)
                self.client = gspread.authorize(creds)
                logger.info("Google Sheets authenticated with service account")
                return True
            
            # Fallback to credentials.json (OAuth)
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
            logger.error("Google Sheets client not authenticated")
            return None, None
        
        try:
            # Open the spreadsheet by key
            sheet = self.client.open_by_key(self.sheet_key)
            logger.info(f"✅ Spreadsheet opened successfully: {sheet.title}")
            
            # Get tickets data (assuming first worksheet contains tickets)
            tickets_worksheet = sheet.get_worksheet(0)  # First sheet
            tickets_data = tickets_worksheet.get_all_values()
            
            # Try to get interactions data (assuming second worksheet)
            try:
                interactions_worksheet = sheet.get_worksheet(1)  # Second sheet
                interactions_data = interactions_worksheet.get_all_values()
            except:
                # If no second sheet, create empty interactions
                interactions_data = [['message_id', 'date', 'author_id', 'author_name', 'author_company', 'body', 'message_type', 'ticket_id']]
                logger.warning("No interactions sheet found, using empty data")
            
            logger.info(f"✅ Retrieved {len(tickets_data)} ticket rows and {len(interactions_data)} interaction rows")
            
            return tickets_data, interactions_data
            
        except gspread.SpreadsheetNotFound:
            logger.error("❌ Spreadsheet not found. Check sheet key and share settings.")
            return None, None
        except Exception as e:
            logger.error(f"❌ Error reading Google Sheets data: {e}")
            return None, None


class HelpdeskDataManager:
    """Manages helpdesk data loading and processing"""
    
    def __init__(self):
        self.tickets_df = None
        self.interactions_df = None
        self.data_source = "unknown"
        self.sheets_manager = GoogleSheetsManager()
        self.load_data()
    
    def load_data(self):
        """Load data with priority: Google Sheets -> Local file -> Sample data"""
        
        # Priority 1: Google Sheets
        if self._try_google_sheets():
            self.data_source = "google_sheets"
            return
        
        # Priority 2: Local Excel file
        local_path = 'data/helpdesk_dataset.xlsx'
        if os.path.exists(local_path):
            try:
                logger.info(f"Loading data from local file: {local_path}")
                self._load_from_local_file(local_path)
                self.data_source = "local_file"
                return
            except Exception as e:
                logger.error(f"Error loading local file: {e}")
        
        # Priority 3: Create sample data as fallback
        logger.warning("No data source available, creating sample data")
        self._create_sample_data()
        self.data_source = "sample_data"
    
    def _try_google_sheets(self):
        """Try to load from Google Sheets"""
        try:
            if not self.sheets_manager.client:
                logger.info("Google Sheets not configured, skipping")
                return False
            
            tickets_data, interactions_data = self.sheets_manager.get_sheet_data()
            
            if not tickets_data:
                logger.warning("No data retrieved from Google Sheets")
                return False
            
            # Convert to DataFrames
            if len(tickets_data) > 1:  # Has header + data
                tickets_df = pd.DataFrame(tickets_data[1:], columns=tickets_data[0])
                self.tickets_df = tickets_df
                logger.info(f"✅ Loaded {len(self.tickets_df)} tickets from Google Sheets")
            
            if interactions_data and len(interactions_data) > 1:
                interactions_df = pd.DataFrame(interactions_data[1:], columns=interactions_data[0])
                self.interactions_df = interactions_df
                logger.info(f"✅ Loaded {len(self.interactions_df)} interactions from Google Sheets")
            else:
                # Create empty interactions DataFrame
                self.interactions_df = pd.DataFrame(columns=['message_id', 'date', 'author_id', 'author_name', 'author_company', 'body', 'message_type', 'ticket_id'])
            
            # Clean and preprocess data
            self._preprocess_data()
            
            return True
            
        except Exception as e:
            logger.error(f"Error loading from Google Sheets: {e}")
            return False
    
    def _load_from_local_file(self, file_path: str):
        """Load data from local Excel file"""
        try:
            # Load tickets sheet
            self.tickets_df = pd.read_excel(file_path, sheet_name='Tickets')
            logger.info(f"Loaded {len(self.tickets_df)} tickets from local file")
            
            # Load interactions sheet
            try:
                self.interactions_df = pd.read_excel(file_path, sheet_name='Interactions')
                logger.info(f"Loaded {len(self.interactions_df)} interactions from local file")
            except:
                self.interactions_df = pd.DataFrame(columns=['message_id', 'date', 'author_id', 'author_name', 'author_company', 'body', 'message_type', 'ticket_id'])
                logger.warning("No interactions sheet found in local file")
            
            # Clean and preprocess data
            self._preprocess_data()
            
        except Exception as e:
            logger.error(f"Error loading from local file: {e}")
            raise e
    
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
        
        # Clean descriptions (remove HTML tags)
        if 'description' in self.tickets_df.columns:
            self.tickets_df['description_clean'] = self.tickets_df['description'].apply(self._clean_description)
        else:
            self.tickets_df['description_clean'] = ''
        
        # Clean stage names
        if 'stage_name' in self.tickets_df.columns:
            self.tickets_df['stage_clean'] = self.tickets_df['stage_name'].apply(self._clean_stage_name)
        else:
            self.tickets_df['stage_clean'] = 'New'
        
        # Add categorization
        self.tickets_df['is_functional'] = self.tickets_df['description_clean'].apply(self._is_functional_issue)
        self.tickets_df['is_technical'] = self.tickets_df['description_clean'].apply(self._is_technical_issue)
        
        # Convert dates
        date_columns = ['create_date', 'close_date']
        for col in date_columns:
            if col in self.tickets_df.columns:
                self.tickets_df[col] = pd.to_datetime(self.tickets_df[col], errors='coerce')
        
        logger.info("Data preprocessing completed successfully")
    
    def _clean_team_name(self, team_name) -> str:
        """Extract clean team name from the multilingual format"""
        if pd.isna(team_name) or not team_name:
            return 'DevOps'
        
        team_str = str(team_name)
        if 'Integration 1' in team_str or 'Intégration 1' in team_str:
            return 'Integration 1'
        elif 'Integration 2' in team_str or 'Intégration 2' in team_str:
            return 'Integration 2'
        elif 'DevOps' in team_str:
            return 'DevOps'
        
        return 'DevOps'
    
    def _clean_description(self, description) -> str:
        """Remove HTML tags from description"""
        if pd.isna(description) or not description:
            return ''
        
        # Remove HTML tags
        clean_desc = re.sub(r'<[^>]+>', '', str(description))
        return clean_desc.strip()
    
    def _clean_stage_name(self, stage_name) -> str:
        """Extract clean stage name from multilingual format"""
        if pd.isna(stage_name) or not stage_name:
            return 'New'
        
        stage_str = str(stage_name)
        if 'In Progress' in stage_str or 'En cours' in stage_str:
            return 'In Progress'
        elif 'Closed' in stage_str or 'Cloturé' in stage_str:
            return 'Closed'
        
        return 'New'
    
    def _is_functional_issue(self, description) -> bool:
        """Detect if issue is functional based on keywords"""
        if pd.isna(description) or not description:
            return False
        
        functional_keywords = [
            'dashboard', 'interface', 'menu', 'écran', 'affichage', 
            'navigation', 'bouton', 'formulaire', 'page', 'visibles'
        ]
        
        description_lower = str(description).lower()
        return any(keyword in description_lower for keyword in functional_keywords)
    
    def _is_technical_issue(self, description) -> bool:
        """Detect if issue is technical based on keywords"""
        if pd.isna(description) or not description:
            return False
        
        technical_keywords = [
            'api', 'webhook', 'synchronisation', 'base de données', 
            'serveur', 'erreur système', 'crash', 'migration', 'journal',
            'e-commerce', 'comptable'
        ]
        
        description_lower = str(description).lower()
        return any(keyword in description_lower for keyword in technical_keywords)
    
    def _create_sample_data(self):
        """Create sample data if no file is available"""
        logger.info("Creating sample data for demonstration")
        
        sample_tickets = [
            {
                'ticket_id': 30000,
                'ticket_subject': 'Synchronisation e-commerce',
                'customer': 'ACME Corp',
                'customer_email': 'it@acme.com',
                'team_name': "{'en_US': 'Integration 1', 'fr_FR': 'Intégration 1'}",
                'team_clean': 'Integration 1',
                'priority': 1,
                'priority_text': 'Medium',
                'create_date': pd.Timestamp('2025-05-29 22:22:08'),
                'close_date': None,
                'stage_name': "{'en_US': 'In Progress', 'fr_FR': 'En cours'}",
                'stage_clean': 'In Progress',
                'description': '<p>Contexte: après migration, plusieurs anomalies constatées.</p>',
                'description_clean': 'Contexte: après migration, plusieurs anomalies constatées.',
                'is_functional': False,
                'is_technical': True
            },
            {
                'ticket_id': 30001,
                'ticket_subject': 'Erreurs dashboard utilisateur',
                'customer': 'TechCorp',
                'customer_email': 'support@techcorp.com',
                'team_name': "{'en_US': 'Integration 1', 'fr_FR': 'Intégration 1'}",
                'team_clean': 'Integration 1',
                'priority': 2,
                'priority_text': 'High',
                'create_date': pd.Timestamp('2025-05-30 10:15:00'),
                'close_date': None,
                'stage_name': "{'en_US': 'New', 'fr_FR': 'Nouveau'}",
                'stage_clean': 'New',
                'description': '<p>Le dashboard principal ne s\'affiche plus correctement après la mise à jour.</p>',
                'description_clean': 'Le dashboard principal ne s\'affiche plus correctement après la mise à jour.',
                'is_functional': True,
                'is_technical': False
            },
            {
                'ticket_id': 30002,
                'ticket_subject': 'Problème webhook API',
                'customer': 'DataFlow Inc',
                'customer_email': 'tech@dataflow.com',
                'team_name': "{'en_US': 'Integration 2', 'fr_FR': 'Intégration 2'}",
                'team_clean': 'Integration 2',
                'priority': 3,
                'priority_text': 'Urgent',
                'create_date': pd.Timestamp('2025-05-31 14:30:00'),
                'close_date': None,
                'stage_name': "{'en_US': 'New', 'fr_FR': 'Nouveau'}",
                'stage_clean': 'New',
                'description': '<p>Les webhooks ne sont plus reçus depuis ce matin. Impact critique sur la production.</p>',
                'description_clean': 'Les webhooks ne sont plus reçus depuis ce matin. Impact critique sur la production.',
                'is_functional': False,
                'is_technical': True
            }
        ]
        
        self.tickets_df = pd.DataFrame(sample_tickets)
        
        # Sample interactions
        sample_interactions = [
            {
                'message_id': 500001,
                'date': '2025-06-07T14:59:39.000Z',
                'author_id': 104,
                'author_name': 'Support Agent',
                'author_company': 'Karizma Conseil',
                'body': 'Ticket créé automatiquement',
                'message_type': 'notification',
                'ticket_id': 30000
            }
        ]
        
        self.interactions_df = pd.DataFrame(sample_interactions)
    
    def get_ticket_by_id(self, ticket_id: int) -> Optional[Dict]:
        """Get a specific ticket by ID"""
        if self.tickets_df is None:
            return None
            
        ticket_row = self.tickets_df[self.tickets_df['ticket_id'] == ticket_id]
        
        if ticket_row.empty:
            return None
        
        ticket_dict = ticket_row.iloc[0].to_dict()
        
        # Convert Timestamp objects to strings for JSON serialization
        for key, value in ticket_dict.items():
            if pd.isna(value):
                ticket_dict[key] = None
            elif isinstance(value, pd.Timestamp):
                ticket_dict[key] = value.isoformat()
        
        return ticket_dict
    
    def get_all_tickets(self, limit: int = 50) -> List[Dict]:
        """Get all tickets with optional limit"""
        if self.tickets_df is None:
            return []
        
        tickets = self.tickets_df.head(limit).to_dict('records')
        
        # Convert Timestamp objects to strings for JSON serialization
        for ticket in tickets:
            for key, value in ticket.items():
                if pd.isna(value):
                    ticket[key] = None
                elif isinstance(value, pd.Timestamp):
                    ticket[key] = value.isoformat()
        
        return tickets
    
    def reload_data(self):
        """Reload data from source"""
        logger.info("Reloading data...")
        self.tickets_df = None
        self.interactions_df = None
        self.load_data()


class EmailTemplateManager:
    """Manages email templates for different response types"""
    
    def __init__(self):
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
    
    def get_template(self, response_type: str) -> Optional[Dict]:
        """Get email template by response type"""
        return self.templates.get(response_type)
    
    def get_all_templates(self) -> Dict:
        """Get all available templates"""
        return self.templates


class GPTContentGenerator:
    """Handles GPT content generation"""
    
    def __init__(self):
        self.client = openai
    
    def generate_content(self, ticket: Dict, response_type: str) -> str:
        """Generate contextual content using GPT"""
        try:
            if not openai.api_key or openai.api_key in ['your-openai-api-key-here', None]:
                logger.warning("OpenAI API key not configured, using fallback content")
                return self._get_fallback_content(ticket, response_type)
            
            prompt = self._create_prompt(ticket, response_type)
            
            response = self.client.chat.completions.create(
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
    
    def _create_prompt(self, ticket: Dict, response_type: str) -> str:
        """Create GPT prompt based on ticket and response type"""
        return f"""
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
Ne commence pas par "Nous comprenons" mais sois créatif et professionnel.
"""
    
    def _get_fallback_content(self, ticket: Dict, response_type: str) -> str:
        """Provide fallback content if GPT fails"""
        subject = ticket.get('ticket_subject', 'votre demande')
        
        fallback_map = {
            'urgent_acknowledgment': f"Cette situation requiert notre attention immédiate et nous mobilisons dès maintenant toutes nos ressources pour vous apporter une solution rapide. Notre équipe technique spécialisée va prendre contact avec vous dans les plus brefs délais.",
            
            'clarification_request': f"Afin de vous proposer la solution la plus adaptée à vos besoins, nous souhaiterions obtenir quelques informations complémentaires concernant votre environnement et les circonstances de ce problème. Un membre de notre équipe va vous contacter prochainement.",
            
            'standard_acknowledgment': f"Nous avons assigné votre demande à notre équipe technique qui possède l'expertise nécessaire pour résoudre ce type de problématique. Nous vous tiendrons informé régulièrement de l'avancement de la résolution."
        }
        
        return fallback_map.get(response_type, f"Nous prenons en charge votre demande avec toute l'attention qu'elle mérite et vous tiendrons informé de son évolution.")


class WorkflowEngine:
    """Main workflow engine for processing helpdesk tickets"""
    
    def __init__(self, data_manager: HelpdeskDataManager, template_manager: EmailTemplateManager, gpt_generator: GPTContentGenerator):
        self.data_manager = data_manager
        self.template_manager = template_manager
        self.gpt_generator = gpt_generator
        self.drafts = {}  # In-memory storage for drafts
    
    def determine_response_type(self, ticket: Dict) -> Tuple[str, str]:
        """Determine the appropriate response type based on ticket analysis"""
        priority = ticket.get('priority_text', 'Medium')
        is_functional = ticket.get('is_functional', False)
        is_technical = ticket.get('is_technical', False)
        
        # Decision logic as per specifications
        if priority in ['Urgent', 'High']:
            return 'urgent_acknowledgment', f"Priority is {priority}, requires urgent response"
        elif is_functional:
            return 'clarification_request', 'Functional issue detected, clarification needed'
        elif is_technical and priority in ['Low', 'Medium']:
            return 'standard_acknowledgment', 'Technical non-urgent issue, standard acknowledgment'
        else:
            return 'standard_acknowledgment', 'Standard processing'
    
    def process_manual_workflow(self, ticket_id: int) -> Dict:
        """Process the complete manual workflow for a ticket"""
        try:
            # 1. Retrieve ticket
            ticket = self.data_manager.get_ticket_by_id(ticket_id)
            if not ticket:
                raise ValueError(f"Ticket {ticket_id} not found")
            
            # 2. Preprocessing is already done during data loading
            
            # 3. Determine response type
            response_type, reasoning = self.determine_response_type(ticket)
            
            # 4. Get template
            template = self.template_manager.get_template(response_type)
            if not template:
                raise ValueError(f"Template {response_type} not found")
            
            # 5. Generate GPT content
            gpt_content = self.gpt_generator.generate_content(ticket, response_type)
            
            # 6. Merge template with content
            final_email = self._merge_template_content(ticket, template, gpt_content)
            
            # 7. Create draft
            draft_id = self._create_draft(final_email, ticket_id)
            
            return {
                'success': True,
                'workflow_id': f"workflow_{int(datetime.now().timestamp())}",
                'ticket': ticket,
                'response_type': response_type,
                'reasoning': reasoning,
                'gpt_content': gpt_content,
                'final_email': final_email,
                'draft_id': draft_id
            }
            
        except Exception as e:
            logger.error(f"Error in manual workflow: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def _merge_template_content(self, ticket: Dict, template: Dict, gpt_content: str) -> Dict:
        """Merge template with ticket data and GPT content"""
        placeholders = {
            'ticket_id': ticket.get('ticket_id', ''),
            'customer_name': ticket.get('customer', ''),
            'issue': ticket.get('ticket_subject', ''),
            'team': ticket.get('team_clean', ''),
            'gpt_content': gpt_content
        }
        
        # Replace placeholders in subject
        subject = template['subject'].format(**placeholders)
        
        # Replace placeholders in body
        body = template['body'].format(**placeholders)
        
        return {
            'to': ticket.get('customer_email', ''),
            'subject': subject,
            'body': body,
            'ticket_id': ticket.get('ticket_id', '')
        }
    
    def _create_draft(self, email_content: Dict, ticket_id: int) -> str:
        """Create email draft"""
        draft_id = f"draft_{uuid.uuid4().hex[:8]}"
        
        self.drafts[draft_id] = {
            'id': draft_id,
            'email_content': email_content,
            'ticket_id': ticket_id,
            'status': 'draft',
            'created_at': datetime.now().isoformat()
        }
        
        return draft_id
    
    def get_draft(self, draft_id: str) -> Optional[Dict]:
        """Get draft by ID"""
        return self.drafts.get(draft_id)
    
    def validate_and_send_draft(self, draft_id: str, action: str = 'send', modifications: Dict = None) -> Dict:
        """Validate and send email draft"""
        draft = self.get_draft(draft_id)
        if not draft:
            return {'success': False, 'error': 'Draft not found'}
        
        try:
            if action == 'send':
                # In a real implementation, you would send the actual email here
                logger.info(f"Email would be sent: {draft['email_content']['subject']}")
                
                # Update draft status
                self.drafts[draft_id]['status'] = 'sent'
                self.drafts[draft_id]['sent_at'] = datetime.now().isoformat()
                
                return {
                    'success': True,
                    'message': 'Email sent successfully',
                    'draft_id': draft_id,
                    'action': 'sent'
                }
            
            elif action == 'edit':
                if modifications:
                    # Apply modifications to the draft
                    for key, value in modifications.items():
                        if key in draft['email_content']:
                            draft['email_content'][key] = value
                    
                    self.drafts[draft_id]['modified_at'] = datetime.now().isoformat()
                
                return {
                    'success': True,
                    'message': 'Draft updated with modifications',
                    'draft_id': draft_id,
                    'modifications': modifications,
                    'action': 'edited'
                }
            
            else:  # cancel
                self.drafts[draft_id]['status'] = 'cancelled'
                self.drafts[draft_id]['cancelled_at'] = datetime.now().isoformat()
                
                return {
                    'success': True,
                    'message': 'Draft cancelled',
                    'draft_id': draft_id,
                    'action': 'cancelled'
                }
                
        except Exception as e:
            logger.error(f"Error in validation: {e}")
            return {'success': False, 'error': str(e)}


# Initialize global objects
data_manager = HelpdeskDataManager()
template_manager = EmailTemplateManager()
gpt_generator = GPTContentGenerator()
workflow_engine = WorkflowEngine(data_manager, template_manager, gpt_generator)

# =============================================================================
# API ENDPOINTS
# =============================================================================

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    google_sheets_connected = data_manager.data_source == "google_sheets"
    local_file_loaded = data_manager.data_source == "local_file"
    
    return jsonify({
        'status': 'OK',
        'timestamp': datetime.now().isoformat(),
        'tickets_loaded': len(data_manager.tickets_df) if data_manager.tickets_df is not None else 0,
        'data_source': data_manager.data_source,
        'google_sheets_connected': google_sheets_connected,
        'local_file_loaded': local_file_loaded,
        'openai_configured': openai.api_key is not None and openai.api_key not in ['your-openai-api-key-here'],
        'sheets_key': data_manager.sheets_manager.sheet_key if google_sheets_connected else None
    })

@app.route('/api/tickets', methods=['GET'])
def get_tickets():
    """Get all tickets with optional filtering and pagination"""
    try:
        limit = request.args.get('limit', 20, type=int)
        priority = request.args.get('priority')
        team = request.args.get('team')
        stage = request.args.get('stage')
        
        tickets = data_manager.get_all_tickets(limit)
        
        # Apply filters if provided
        if priority:
            tickets = [t for t in tickets if t.get('priority_text') == priority]
        if team:
            tickets = [t for t in tickets if t.get('team_clean') == team]
        if stage:
            tickets = [t for t in tickets if t.get('stage_clean') == stage]
        
        return jsonify({
            'success': True,
            'tickets': tickets,
            'total': len(data_manager.tickets_df) if data_manager.tickets_df is not None else 0,
            'filtered_count': len(tickets),
            'data_source': data_manager.data_source
        })
    except Exception as e:
        logger.error(f"Error getting tickets: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/tickets/<int:ticket_id>', methods=['GET'])
def get_ticket(ticket_id):
    """Get specific ticket by ID"""
    try:
        ticket = data_manager.get_ticket_by_id(ticket_id)
        
        if not ticket:
            return jsonify({'success': False, 'error': 'Ticket not found'}), 404
        
        return jsonify({
            'success': True,
            'ticket': ticket
        })
    except Exception as e:
        logger.error(f"Error getting ticket {ticket_id}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# =============================================================================
# MANUAL WORKFLOW ENDPOINTS
# =============================================================================

@app.route('/api/manual/trigger', methods=['POST'])
def manual_trigger():
    """Webhook/Trigger endpoint - Start manual workflow"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No JSON data provided'}), 400
        
        ticket_id = data.get('ticket_id')
        
        if not ticket_id:
            return jsonify({'success': False, 'error': 'ticket_id is required'}), 400
        
        # Check if ticket exists
        ticket = data_manager.get_ticket_by_id(int(ticket_id))
        if not ticket:
            return jsonify({'success': False, 'error': 'Ticket not found'}), 404
        
        workflow_id = f"workflow_{int(datetime.now().timestamp())}"
        
        logger.info(f"Manual workflow triggered for ticket {ticket_id}")
        
        return jsonify({
            'success': True,
            'workflow_id': workflow_id,
            'ticket': ticket,
            'message': 'Manual workflow triggered successfully'
        })
        
    except Exception as e:
        logger.error(f"Error in manual trigger: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/manual/preprocess', methods=['POST'])
def preprocess_ticket():
    """Preprocess ticket data (normalization and cleaning)"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No JSON data provided'}), 400
        
        ticket = data.get('ticket')
        
        if not ticket:
            return jsonify({'success': False, 'error': 'ticket data is required'}), 400
        
        # The preprocessing is already done during data loading
        # But we can add additional preprocessing here if needed
        preprocessed = {
            **ticket,
            'preprocessed_at': datetime.now().isoformat(),
            'preprocessing_status': 'completed'
        }
        
        return jsonify({
            'success': True,
            'preprocessed_data': preprocessed,
            'message': 'Ticket preprocessed successfully'
        })
        
    except Exception as e:
        logger.error(f"Error in preprocessing: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/manual/response-type', methods=['POST'])
def determine_response_type():
    """Determine response type based on ticket analysis (Decision node)"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No JSON data provided'}), 400
        
        ticket = data.get('ticket')
        
        if not ticket:
            return jsonify({'success': False, 'error': 'ticket data is required'}), 400
        
        response_type, reasoning = workflow_engine.determine_response_type(ticket)
        
        logger.info(f"Response type determined: {response_type} for ticket {ticket.get('ticket_id')}")
        
        return jsonify({
            'success': True,
            'response_type': response_type,
            'reasoning': reasoning,
            'ticket_id': ticket.get('ticket_id'),
            'priority': ticket.get('priority_text'),
            'is_functional': ticket.get('is_functional'),
            'is_technical': ticket.get('is_technical')
        })
        
    except Exception as e:
        logger.error(f"Error determining response type: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/templates', methods=['GET'])
def get_templates():
    """Get all email templates"""
    try:
        templates = template_manager.get_all_templates()
        
        return jsonify({
            'success': True,
            'templates': templates,
            'template_count': len(templates)
        })
        
    except Exception as e:
        logger.error(f"Error getting templates: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/templates/<response_type>', methods=['GET'])
def get_template(response_type):
    """Get specific email template by response type"""
    try:
        template = template_manager.get_template(response_type)
        
        if not template:
            return jsonify({'success': False, 'error': 'Template not found'}), 404
        
        return jsonify({
            'success': True,
            'template': template,
            'response_type': response_type
        })
        
    except Exception as e:
        logger.error(f"Error getting template {response_type}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/manual/generate-content', methods=['POST'])
def generate_gpt_content():
    """Generate GPT content for email (OpenAI node)"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No JSON data provided'}), 400
        
        ticket = data.get('ticket')
        response_type = data.get('response_type')
        
        if not ticket or not response_type:
            return jsonify({'success': False, 'error': 'ticket and response_type are required'}), 400
        
        logger.info(f"Generating GPT content for ticket {ticket.get('ticket_id')} with response type {response_type}")
        
        generated_content = gpt_generator.generate_content(ticket, response_type)
        
        return jsonify({
            'success': True,
            'generated_content': generated_content,
            'ticket_id': ticket.get('ticket_id'),
            'response_type': response_type,
            'generation_timestamp': datetime.now().isoformat()
        })
        
    except Exception as e:
        logger.error(f"Error generating GPT content: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/manual/merge-content', methods=['POST'])
def merge_content():
    """Merge template with GPT content and ticket data (Function node)"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No JSON data provided'}), 400
        
        ticket = data.get('ticket')
        template = data.get('template')
        generated_content = data.get('generated_content')
        
        if not ticket or not template or not generated_content:
            return jsonify({'success': False, 'error': 'ticket, template, and generated_content are required'}), 400
        
        final_email = workflow_engine._merge_template_content(ticket, template, generated_content)
        
        logger.info(f"Content merged for ticket {ticket.get('ticket_id')}")
        
        return jsonify({
            'success': True,
            'final_email': final_email,
            'merge_timestamp': datetime.now().isoformat()
        })
        
    except Exception as e:
        logger.error(f"Error merging content: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/manual/create-draft', methods=['POST'])
def create_draft():
    """Create email draft (Gmail/IMAP node simulation)"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No JSON data provided'}), 400
        
        email_content = data.get('email_content')
        ticket_id = data.get('ticket_id')
        
        if not email_content:
            return jsonify({'success': False, 'error': 'email_content is required'}), 400
        
        draft_id = workflow_engine._create_draft(email_content, ticket_id)
        draft = workflow_engine.get_draft(draft_id)
        
        logger.info(f"Draft created with ID: {draft_id} for ticket {ticket_id}")
        
        return jsonify({
            'success': True,
            'draft_id': draft_id,
            'draft': draft,
            'message': 'Draft created successfully'
        })
        
    except Exception as e:
        logger.error(f"Error creating draft: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/drafts/<draft_id>', methods=['GET'])
def get_draft(draft_id):
    """Get draft by ID"""
    try:
        draft = workflow_engine.get_draft(draft_id)
        
        if not draft:
            return jsonify({'success': False, 'error': 'Draft not found'}), 404
        
        return jsonify({
            'success': True,
            'draft': draft
        })
        
    except Exception as e:
        logger.error(f"Error getting draft {draft_id}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/manual/notify-validation', methods=['POST'])
def notify_validation():
    """Send validation notification to supervisor"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No JSON data provided'}), 400
        
        draft_id = data.get('draft_id')
        ticket_id = data.get('ticket_id')
        
        if not draft_id:
            return jsonify({'success': False, 'error': 'draft_id is required'}), 400
        
        # Verify draft exists
        draft = workflow_engine.get_draft(draft_id)
        if not draft:
            return jsonify({'success': False, 'error': 'Draft not found'}), 404
        
        # In a real implementation, this would send an actual notification
        # For now, we'll simulate the notification
        logger.info(f"Validation notification sent for draft {draft_id}, ticket {ticket_id}")
        
        notification_info = {
            'draft_id': draft_id,
            'ticket_id': ticket_id,
            'notification_sent_at': datetime.now().isoformat(),
            'notification_type': 'validation_request',
            'status': 'pending_validation'
        }
        
        return jsonify({
            'success': True,
            'message': 'Validation notification sent successfully',
            'notification_info': notification_info
        })
        
    except Exception as e:
        logger.error(f"Error sending validation notification: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/manual/validate-send', methods=['POST'])
def validate_and_send():
    """Validate and send email (manual validation step)"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No JSON data provided'}), 400
        
        draft_id = data.get('draft_id')
        action = data.get('action', 'send')  # 'send', 'edit', 'cancel'
        modifications = data.get('modifications', {})
        
        if not draft_id:
            return jsonify({'success': False, 'error': 'draft_id is required'}), 400
        
        result = workflow_engine.validate_and_send_draft(draft_id, action, modifications)
        
        logger.info(f"Draft {draft_id} action: {action}")
        
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Error in validate and send: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/manual/complete-workflow', methods=['POST'])
def complete_workflow():
    """Execute the complete manual workflow end-to-end"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No JSON data provided'}), 400
        
        ticket_id = data.get('ticket_id')
        
        if not ticket_id:
            return jsonify({'success': False, 'error': 'ticket_id is required'}), 400
        
        logger.info(f"Starting complete workflow for ticket {ticket_id}")
        
        # Execute the complete workflow
        result = workflow_engine.process_manual_workflow(int(ticket_id))
        
        if result['success']:
            logger.info(f"Complete workflow finished successfully for ticket {ticket_id}")
        else:
            logger.error(f"Complete workflow failed for ticket {ticket_id}: {result.get('error')}")
        
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Error in complete workflow: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# =============================================================================
# UTILITY AND DATA ENDPOINTS
# =============================================================================

@app.route('/api/stats', methods=['GET'])
def get_stats():
    """Get helpdesk statistics"""
    try:
        if data_manager.tickets_df is None:
            return jsonify({'success': False, 'error': 'No data available'}), 404
        
        df = data_manager.tickets_df
        
        stats = {
            'total_tickets': len(df),
            'priority_distribution': df['priority_text'].value_counts().to_dict(),
            'team_distribution': df['team_clean'].value_counts().to_dict(),
            'stage_distribution': df['stage_clean'].value_counts().to_dict(),
            'functional_issues': int(df['is_functional'].sum()),
            'technical_issues': int(df['is_technical'].sum()),
            'urgent_tickets': len(df[df['priority_text'] == 'Urgent']),
            'high_priority_tickets': len(df[df['priority_text'] == 'High']),
            'open_tickets': len(df[df['stage_clean'] != 'Closed']),
            'closed_tickets': len(df[df['stage_clean'] == 'Closed']),
            'data_source': data_manager.data_source
        }
        
        return jsonify({
            'success': True,
            'stats': stats,
            'generated_at': datetime.now().isoformat()
        })
        
    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/reload-data', methods=['POST'])
def reload_data():
    """Reload data from Google Sheets"""
    try:
        logger.info("Reloading data from Google Sheets...")
        
        # Reload data
        data_manager.reload_data()
        
        return jsonify({
            'success': True,
            'message': 'Data reloaded successfully',
            'tickets_loaded': len(data_manager.tickets_df) if data_manager.tickets_df is not None else 0,
            'data_source': data_manager.data_source,
            'reload_timestamp': datetime.now().isoformat()
        })
        
    except Exception as e:
        logger.error(f"Error reloading data: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/test-gpt', methods=['POST'])
def test_gpt():
    """Test GPT content generation"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No JSON data provided'}), 400
        
        test_ticket = {
            'ticket_id': 99999,
            'customer': 'Test Client',
            'ticket_subject': 'Test Issue',
            'priority_text': 'Medium',
            'description_clean': 'This is a test ticket for GPT generation',
            'team_clean': 'Integration 1'
        }
        
        response_type = data.get('response_type', 'standard_acknowledgment')
        
        generated_content = gpt_generator.generate_content(test_ticket, response_type)
        
        return jsonify({
            'success': True,
            'generated_content': generated_content,
            'test_ticket': test_ticket,
            'response_type': response_type,
            'openai_configured': openai.api_key is not None and openai.api_key not in ['your-openai-api-key-here']
        })
        
    except Exception as e:
        logger.error(f"Error testing GPT: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/test-sheets', methods=['GET'])
def test_sheets():
    """Test Google Sheets connection"""
    try:
        if not data_manager.sheets_manager.client:
            return jsonify({
                'success': False,
                'error': 'Google Sheets not configured',
                'message': 'Add service_account.json or credentials.json file'
            }), 400
        
        # Test connection by getting sheet info
        sheet = data_manager.sheets_manager.client.open_by_key(data_manager.sheets_manager.sheet_key)
        
        worksheets = []
        for ws in sheet.worksheets():
            worksheets.append({
                'title': ws.title,
                'rows': ws.row_count,
                'cols': ws.col_count
            })
        
        return jsonify({
            'success': True,
            'sheet_title': sheet.title,
            'sheet_key': data_manager.sheets_manager.sheet_key,
            'worksheets': worksheets,
            'message': 'Google Sheets connection successful'
        })
        
    except Exception as e:
        logger.error(f"Error testing Google Sheets: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/data-info', methods=['GET'])
def get_data_info():
    """Get information about loaded data"""
    try:
        if data_manager.tickets_df is None:
            return jsonify({'success': False, 'error': 'No data available'}), 404
        
        df = data_manager.tickets_df
        
        # Get sample tickets for each priority
        sample_tickets = {}
        for priority in df['priority_text'].unique():
            sample = df[df['priority_text'] == priority].head(1).to_dict('records')
            if sample:
                sample_tickets[priority] = sample[0]['ticket_id']
        
        info = {
            'data_source': data_manager.data_source,
            'total_tickets': len(df),
            'columns': list(df.columns),
            'date_range': {
                'oldest': df['create_date'].min().isoformat() if 'create_date' in df.columns and not df['create_date'].isna().all() else None,
                'newest': df['create_date'].max().isoformat() if 'create_date' in df.columns and not df['create_date'].isna().all() else None
            },
            'sample_ticket_ids': sample_tickets,
            'unique_customers': df['customer'].nunique() if 'customer' in df.columns else 0,
            'unique_teams': list(df['team_clean'].unique()) if 'team_clean' in df.columns else []
        }
        
        return jsonify({
            'success': True,
            'data_info': info
        })
        
    except Exception as e:
        logger.error(f"Error getting data info: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# =============================================================================
# ERROR HANDLERS
# =============================================================================

@app.errorhandler(404)
def not_found(error):
    return jsonify({'success': False, 'error': 'Endpoint not found'}), 404

@app.errorhandler(405)
def method_not_allowed(error):
    return jsonify({'success': False, 'error': 'Method not allowed'}), 405

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"Internal server error: {error}")
    return jsonify({'success': False, 'error': 'Internal server error'}), 500

# =============================================================================
# MAIN APPLICATION STARTUP
# =============================================================================

if __name__ == '__main__':
    # Set up logging
    if not app.debug:
        file_handler = logging.FileHandler('helpdesk_backend.log')
        file_handler.setFormatter(logging.Formatter(
            '%(asctime)s %(levelname)s %(name)s %(threadName)s : %(message)s'
        ))
        app.logger.addHandler(file_handler)
        app.logger.setLevel(logging.INFO)
        logger.addHandler(file_handler)
    
    # Print startup information
    print("=" * 60)
    print("🚀 HELPDESK AI AGENT SUPPORT BACKEND")
    print("=" * 60)
    print(f"📊 Tickets loaded: {len(data_manager.tickets_df) if data_manager.tickets_df is not None else 0}")
    print(f"📁 Data source: {data_manager.data_source.upper()}")
    
    if data_manager.data_source == "google_sheets":
        print("📊 Using Google Sheets")
        print(f"📋 Sheet Key: {data_manager.sheets_manager.sheet_key}")
    elif data_manager.data_source == "local_file":
        print("📂 Using local file: data/helpdesk_dataset.xlsx")
    else:
        print("⚠️  Using sample data (no real data source found)")
    
    print(f"🤖 OpenAI configured: {'✅' if openai.api_key and openai.api_key not in ['your-openai-api-key-here'] else '❌'}")
    print(f"🌐 Server starting on: http://localhost:5000")
    print("=" * 60)
    print("\n📋 AVAILABLE ENDPOINTS:")
    print("Health Check:        GET  /api/health")
    print("Test Sheets:         GET  /api/test-sheets")
    print("Get Tickets:         GET  /api/tickets")
    print("Get Ticket:          GET  /api/tickets/<id>")
    print("Manual Trigger:      POST /api/manual/trigger")
    print("Complete Workflow:   POST /api/manual/complete-workflow")
    print("Get Templates:       GET  /api/templates")
    print("Generate Content:    POST /api/manual/generate-content")
    print("Get Stats:           GET  /api/stats")
    print("Get Data Info:       GET  /api/data-info")
    print("Reload Data:         POST /api/reload-data")
    print("Test GPT:            POST /api/test-gpt")
    print("\n🔧 Setup Instructions:")
    
    if data_manager.data_source == "sample_data":
        print("1. Add service_account.json (preferred) or credentials.json")
        print("2. Set GOOGLE_SHEETS_KEY in .env (current: 1NU0UPK6JMxzlPlnFPm_lD1vBb4zz0sJjJERmertzMGw)")
        print("3. Or place Excel file as: data/helpdesk_dataset.xlsx")
        print("4. Restart: python app.py")
    
    if not openai.api_key or openai.api_key in ['your-openai-api-key-here']:
        print("5. Set OPENAI_API_KEY in .env for GPT functionality")
    
    print("6. Test: curl http://localhost:5000/api/health")
    print("7. Test Sheets: curl http://localhost:5000/api/test-sheets")
    print("=" * 60)
    
    # Show data info if available
    if data_manager.tickets_df is not None and len(data_manager.tickets_df) > 0:
        print(f"\n📋 DATA SUMMARY:")
        df = data_manager.tickets_df
        if not df.empty:
            print(f"  Priorities: {dict(df['priority_text'].value_counts())}")
            print(f"  Teams: {list(df['team_clean'].unique())}")
            if 'ticket_id' in df.columns:
                sample_ids = df['ticket_id'].head(3).tolist()
                print(f"  Sample Ticket IDs: {sample_ids}")
        print("=" * 60)
    
    # Start the Flask application
    app.run(
        host='0.0.0.0',
        port=int(os.environ.get('PORT', 5000)),
        debug=os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    )