from flask import Flask, request, jsonify
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import pickle
import os
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv
load_dotenv()

app = Flask(__name__)

# Google Calendar API scope for full access
SCOPES = ['https://www.googleapis.com/auth/calendar']

# Get secure values from environment variables
API_KEY = os.environ.get('API_KEY', 'dev-key-for-local-testing')
GOOGLE_CREDENTIALS = os.environ.get('GOOGLE_CREDENTIALS')  # JSON string of credentials
GOOGLE_TOKEN = os.environ.get('GOOGLE_TOKEN')  # JSON string of token

def require_api_key(f):
    """Decorator to require API key for endpoints"""
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get('X-API-Key')
        if api_key != API_KEY:
            return jsonify({'success': False, 'error': 'Invalid or missing API key'}), 401
        return f(*args, **kwargs)
    decorated_function.__name__ = f.__name__
    return decorated_function

def get_calendar_service():
    """Authenticate and return Google Calendar service object"""
    creds = None
    
    # Try to load credentials from environment variable first (production)
    if GOOGLE_TOKEN:
        try:
            token_data = json.loads(GOOGLE_TOKEN)
            creds = Credentials.from_authorized_user_info(token_data, SCOPES)
        except Exception as e:
            print(f"Error loading token from environment: {e}")
    
    # Fall back to local file (development)
    elif os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)
    
    # If no valid credentials, request authorization
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            
            # Save refreshed token back to environment (in production this would need a database)
            if GOOGLE_TOKEN:
                # In production, you'd want to update your environment variable
                # For now, we'll just use the refreshed token for this session
                pass
        else:
            # Load credentials from environment or file
            if GOOGLE_CREDENTIALS:
                # Production: load from environment variable
                credentials_data = json.loads(GOOGLE_CREDENTIALS)
                flow = InstalledAppFlow.from_client_config(credentials_data, SCOPES)
            elif os.path.exists('credentials.json'):
                # Development: load from file
                flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            else:
                raise Exception("No credentials found. Set GOOGLE_CREDENTIALS environment variable or provide credentials.json")
            
            # For development, run local server. For production, this won't work.
            if os.path.exists('credentials.json'):
                creds = flow.run_local_server(port=0)
                # Save credentials for next run (development only)
                with open('token.pickle', 'wb') as token:
                    pickle.dump(creds, token)
            else:
                raise Exception("Cannot run OAuth flow in production without local credentials.json")
    
    return build('calendar', 'v3', credentials=creds)

@app.route('/events', methods=['GET'])
@require_api_key
def get_events():
    """Get calendar events"""
    try:
        service = get_calendar_service()
        
        # Parse query parameters
        date_str = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
        days = int(request.args.get('days', 7))
        query = request.args.get('query', '')
        
        # Calculate time range
        start_date = datetime.strptime(date_str, '%Y-%m-%d')
        end_date = start_date + timedelta(days=days)
        
        # Format for Google Calendar API
        time_min = start_date.isoformat() + 'Z'
        time_max = end_date.isoformat() + 'Z'
        
        # Call Google Calendar API
        events_result = service.events().list(
            calendarId='primary',
            timeMin=time_min,
            timeMax=time_max,
            maxResults=50,
            singleEvents=True,
            orderBy='startTime',
            q=query if query else None
        ).execute()
        
        events = events_result.get('items', [])
        
        # Format response
        formatted_events = []
        for event in events:
            formatted_events.append({
                'id': event['id'],
                'title': event.get('summary', 'No title'),
                'start': event['start'].get('dateTime', event['start'].get('date')),
                'end': event['end'].get('dateTime', event['end'].get('date')),
                'description': event.get('description', ''),
                'location': event.get('location', '')
            })
        
        return jsonify({
            'success': True,
            'events': formatted_events,
            'count': len(formatted_events)
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/events', methods=['POST'])
@require_api_key
def create_event():
    """Create a new calendar event"""
    try:
        service = get_calendar_service()
        data = request.json
        
        # Build event object
        event = {
            'summary': data.get('title', 'New Event'),
            'description': data.get('description', ''),
            'location': data.get('location', ''),
        }
        
        # Handle date/time
        if 'date' in data and 'time' in data:
            # Specific date and time
            start_datetime = f"{data['date']}T{data['time']}:00"
            end_datetime = f"{data['date']}T{data.get('end_time', data['time'])}:00"
            event['start'] = {'dateTime': start_datetime, 'timeZone': 'America/New_York'}
            event['end'] = {'dateTime': end_datetime, 'timeZone': 'America/New_York'}
        elif 'date' in data:
            # All-day event
            event['start'] = {'date': data['date']}
            event['end'] = {'date': data['date']}
        
        # Create event
        created_event = service.events().insert(calendarId='primary', body=event).execute()
        
        return jsonify({
            'success': True,
            'event_id': created_event['id'],
            'event_link': created_event.get('htmlLink'),
            'message': f"Event '{data.get('title')}' created successfully"
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/events/<event_id>', methods=['PUT'])
@require_api_key
def update_event(event_id):
    """Update an existing calendar event"""
    try:
        service = get_calendar_service()
        data = request.json
        
        # Get existing event
        event = service.events().get(calendarId='primary', eventId=event_id).execute()
        
        # Update fields
        if 'title' in data:
            event['summary'] = data['title']
        if 'description' in data:
            event['description'] = data['description']
        if 'location' in data:
            event['location'] = data['location']
        
        # Update date/time if provided
        if 'date' in data and 'time' in data:
            start_datetime = f"{data['date']}T{data['time']}:00"
            end_datetime = f"{data['date']}T{data.get('end_time', data['time'])}:00"
            event['start'] = {'dateTime': start_datetime, 'timeZone': 'America/New_York'}
            event['end'] = {'dateTime': end_datetime, 'timeZone': 'America/New_York'}
        
        # Update event
        updated_event = service.events().update(
            calendarId='primary', 
            eventId=event_id, 
            body=event
        ).execute()
        
        return jsonify({
            'success': True,
            'message': f"Event updated successfully",
            'event_link': updated_event.get('htmlLink')
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/events/<event_id>', methods=['DELETE'])
@require_api_key
def delete_event(event_id):
    """Delete a calendar event"""
    try:
        service = get_calendar_service()
        
        # Get event details before deleting (for confirmation)
        event = service.events().get(calendarId='primary', eventId=event_id).execute()
        event_title = event.get('summary', 'Untitled Event')
        
        # Delete event
        service.events().delete(calendarId='primary', eventId=event_id).execute()
        
        return jsonify({
            'success': True,
            'message': f"Event '{event_title}' deleted successfully"
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/events/search', methods=['GET'])
@require_api_key
def search_events():
    """Search for events by query"""
    try:
        service = get_calendar_service()
        query = request.args.get('query', '')
        
        if not query:
            return jsonify({'success': False, 'error': 'Query parameter required'}), 400
        
        # Search events
        events_result = service.events().list(
            calendarId='primary',
            q=query,
            maxResults=25,
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        
        events = events_result.get('items', [])
        
        # Format response
        formatted_events = []
        for event in events:
            formatted_events.append({
                'id': event['id'],
                'title': event.get('summary', 'No title'),
                'start': event['start'].get('dateTime', event['start'].get('date')),
                'end': event['end'].get('dateTime', event['end'].get('date')),
                'description': event.get('description', ''),
                'location': event.get('location', '')
            })
        
        return jsonify({
            'success': True,
            'events': formatted_events,
            'count': len(formatted_events),
            'query': query
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({'status': 'healthy', 'service': 'calendar-api'})

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=8000)