# BloodConnect

BCA Final Year Mini Project: Online Blood Donor & Emergency Blood Request Management System.

## Technology
- Python Flask
- SQLite
- HTML5
- CSS3
- JavaScript
- Google Maps JavaScript API (map UI)

## Features
- Donor registration and login
- Blood group based donor search
- Emergency blood request
- Donor availability status
- Map-based donor location view
- Admin dashboard
- Request status management
- SQLite database

## Run
```bash
python -m venv venv
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

pip install -r requirements.txt
python app.py
```

Open: http://127.0.0.1:5000/

## Admin
The first app start creates a demo admin account:

- Email: `admin@bloodconnect.com`
- Password: `admin123`

For production, change this password and remove the demo credentials from the login page.

You can also promote an existing user by opening SQLite and changing the user's role:
Example:
```sql
UPDATE users SET role='admin' WHERE email='admin@example.com';
```

The app automatically creates `bloodconnect.db` on first run.

## Google Maps Setup
Replace `YOUR_GOOGLE_MAPS_API_KEY` in `templates/base.html` with your Google Maps API key and enable Maps JavaScript API in Google Cloud.
