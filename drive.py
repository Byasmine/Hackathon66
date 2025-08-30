#!/usr/bin/env python3
"""
Quick script to find your Google Drive file ID
Run this to automatically find and configure your Excel file.
"""

import os
import sys

def get_file_id_from_url():
    """Get file ID from Google Drive URL (manual input)"""
    print("📋 Manual File ID Extraction")
    print("=" * 40)
    print("1. Go to Google Drive: https://drive.google.com")
    print("2. Find your Excel file: 'Team 4 Dataset Helpdesk _ Tickets _ Interactions.xlsx'")
    print("3. Right-click → 'Get link' or 'Share'")
    print("4. Copy the link and paste it below")
    print()
    
    url ="https://docs.google.com/spreadsheets/d/1NU0UPK6JMxzlPlnFPm_lD1vBb4zz0sJjJERmertzMGw/edit?gid=0#gid=0"
    
    if not url:
        print("❌ No URL provided")
        return None, None
    
    # Extract file ID from different URL formats
    file_id = None
    
    # Format 1: https://drive.google.com/file/d/FILE_ID/view?usp=sharing
    if "/file/d/" in url:
        try:
            file_id = url.split("/file/d/")[1].split("/")[0]
        except IndexError:
            pass
    
    # Format 2: https://drive.google.com/open?id=FILE_ID
    elif "open?id=" in url:
        try:
            file_id = url.split("open?id=")[1].split("&")[0]
        except IndexError:
            pass
    
    # Format 3: https://docs.google.com/spreadsheets/d/FILE_ID/edit
    elif "/spreadsheets/d/" in url:
        try:
            file_id = url.split("/spreadsheets/d/")[1].split("/")[0]
        except IndexError:
            pass
    
    if file_id:
        print(f"✅ Extracted File ID: {file_id}")
        return file_id, "Team 4 Dataset  Helpdesk _ Tickets _ Interactions.xlsx"
    else:
        print("❌ Could not extract File ID from URL")
        print("   Please make sure the URL is a valid Google Drive link")
        return None, None

def update_env_file(file_id, file_name):
    """Update .env file with Google Drive settings"""
    env_file = '.env'
    
    # Read existing .env or create new one
    env_lines = []
    if os.path.exists(env_file):
        with open(env_file, 'r') as f:
            env_lines = f.readlines()
    
    # Update or add Google Drive settings
    updated_lines = []
    drive_file_id_set = False
    drive_file_name_set = False
    
    for line in env_lines:
        if line.startswith('GOOGLE_DRIVE_FILE_ID='):
            updated_lines.append(f'GOOGLE_DRIVE_FILE_ID={file_id}\n')
            drive_file_id_set = True
        elif line.startswith('GOOGLE_DRIVE_FILE_NAME='):
            updated_lines.append(f'GOOGLE_DRIVE_FILE_NAME={file_name}\n')
            drive_file_name_set = True
        else:
            updated_lines.append(line)
    
    # Add missing entries
    if not drive_file_id_set:
        updated_lines.append(f'GOOGLE_DRIVE_FILE_ID={file_id}\n')
    if not drive_file_name_set:
        updated_lines.append(f'GOOGLE_DRIVE_FILE_NAME={file_name}\n')
    
    # Add other essential settings if .env is new
    if not env_lines:
        updated_lines = [
            '# Flask Configuration\n',
            'FLASK_ENV=development\n',
            'FLASK_DEBUG=True\n',
            'PORT=5000\n',
            '\n',
            '# OpenAI Configuration\n',
            'OPENAI_API_KEY=your-openai-api-key-here\n',
            '\n',
            '# Google Drive Configuration\n',
        ] + updated_lines
    
    # Write back to .env
    with open(env_file, 'w') as f:
        f.writelines(updated_lines)
    
    print(f"✅ Updated {env_file} with Google Drive settings")

def check_dependencies():
    """Check if required packages are installed"""
    required_packages = [
        'google-api-python-client',
        'google-auth',
        'google-auth-oauthlib'
    ]
    
    missing_packages = []
    for package in required_packages:
        try:
            __import__(package.replace('-', '_'))
        except ImportError:
            missing_packages.append(package)
    
    if missing_packages:
        print(f"❌ Missing packages: {', '.join(missing_packages)}")
        print(f"💡 Install with: pip install {' '.join(missing_packages)}")
        return False
    
    return True

def test_google_api():
    """Test Google Drive API connection"""
    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
        
        if not os.path.exists('token.json'):
            print("⚠️  No token.json found. Run full setup to authenticate with Google Drive.")
            return False
        
        creds = Credentials.from_authorized_user_file('token.json')
        service = build('drive', 'v3', credentials=creds)
        
        # Test connection
        results = service.files().list(pageSize=5).execute()
        files = results.get('files', [])
        
        print("✅ Google Drive connection successful!")
        print(f"📁 Found {len(files)} files in your Drive")
        
        return True
        
    except Exception as e:
        print(f"❌ Google Drive connection failed: {e}")
        return False

def main():
    """Main function"""
    print("🔍 Google Drive File ID Finder")
    print("=" * 50)
    print("This script will help you find and configure your Google Drive file.")
    print()
    
    # Check if we can use API method
    if check_dependencies() and os.path.exists('token.json'):
        print("🤖 Option 1: Automatic search (using Google Drive API)")
        print("🔧 Option 2: Manual URL extraction")
        print()
        
        choice = input("Choose option (1 or 2): ").strip()
        
        if choice == "1":
            print("\n🔄 Searching your Google Drive...")
            if test_google_api():
                print("💡 Run the full setup script for automatic file detection:")
                print("   python setup_google_drive.py")
                return
            else:
                print("❌ API search failed, falling back to manual method...")
    else:
        print("🔧 Using manual URL extraction method")
        print("   (Install google-api-python-client for automatic search)")
    
    print()
    
    # Manual method
    file_id, file_name = get_file_id_from_url()
    
    if file_id:
        print()
        print("📝 Updating configuration...")
        update_env_file(file_id, file_name)
        
        print()
        print("🎉 Configuration Updated!")
        print("=" * 30)
        print(f"📁 File ID: {file_id}")
        print(f"📄 File Name: {file_name}")
        print()
        print("🚀 Next steps:")
        print("1. Set your OPENAI_API_KEY in .env file")
        print("2. Run: python app.py")
        print("3. Test: curl http://localhost:5000/api/health")
        
        # Show current .env status
        print()
        print("📋 Current .env file:")
        if os.path.exists('.env'):
            with open('.env', 'r') as f:
                for line in f:
                    if line.startswith(('GOOGLE_DRIVE_', 'OPENAI_API_')):
                        key, value = line.strip().split('=', 1)
                        if 'API_KEY' in key and value != 'your-openai-api-key-here':
                            print(f"  ✅ {key}=***configured***")
                        elif 'API_KEY' in key:
                            print(f"  ⚠️  {key}=***not configured***")
                        else:
                            print(f"  ✅ {key}={value}")
    else:
        print("\n❌ Could not configure Google Drive file.")
        print("💡 Please try again or use the full setup script:")
        print("   python setup_google_drive.py")

if __name__ == '__main__':
    main()