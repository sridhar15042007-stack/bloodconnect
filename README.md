# BloodConnect

BCA Final Year Mini Project: Online Blood Donor & Emergency Blood Request Management System.

## Files

```
bloodconnect/
├── app.py            Flask server + SQLite + JSON API
├── index.html        all pages + the logos (dark, light, icon are inline SVG)
├── style.css         all styles
├── script.js         page routing, API calls, Google Maps
├── bloodconnect.db   SQLite database (created automatically if missing)
└── requirements.txt
```

The logo page (`/#/logo`) has a "Download SVG" button for each logo.

## Page flow
1. **Logo page** (`/`) - full-screen logo, moves on by itself after about 3 seconds or on "Get Started"
2. **Sign In / Sign Up** (`/#/login`, `/#/register`) - one page with two tabs
3. **Dashboard** (`/#/dashboard`) - admin dashboard for the admin account, donor dashboard for everyone else

Home, Find Donor and Blood Request stay in the navbar. Brand logos (download SVG) are linked in the footer (`/#/logo`).

## Technology
- Python Flask
- SQLite
- HTML5 / CSS3 / JavaScript (single page, hash routing)
- Google Maps JavaScript API

## Features
- Donor registration and login
- Blood group based donor search
- Emergency blood request
- Donor availability status
- Map-based request location view
- Admin dashboard
- Request status management

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

For production, change this password and remove the demo credentials from the login page (`index.html`).

You can also promote an existing user by opening SQLite and changing the user's role:
```sql
UPDATE users SET role='admin' WHERE email='admin@example.com';
```

## Google Maps Setup
Set `GOOGLE_MAPS_KEY` at the top of `script.js` and enable the Maps JavaScript API and Geocoding API in Google Cloud. Restrict the key to your site's HTTP referrer.

## JSON API (used by script.js)

| Method | URL | Purpose |
|---|---|---|
| GET | `/api/me` | current logged-in user |
| GET | `/api/home` | recent donors and requests |
| POST | `/api/register` | create donor account |
| POST | `/api/login` / `/api/logout` | session login / logout |
| GET | `/api/profile` | logged-in donor's profile |
| POST | `/api/toggle-availability` | flip Available / Not Available |
| GET | `/api/search?blood_group=&city=` | search available donors |
| POST | `/api/request-blood` | submit a blood request |
| GET | `/api/request/<id>` | one request's details |
| GET | `/api/admin` | admin stats, requests, donors |
| POST | `/api/admin/request/<id>/<status>` | Approved / Completed / Rejected |
