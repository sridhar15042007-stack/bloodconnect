"""
BloodConnect - single-file Flask app.
Everything (routes, HTML templates, CSS, JS) lives in this one file.

Render settings:
  Build command : pip install flask gunicorn
  Start command : gunicorn app:app
  Environment   : SECRET_KEY, ADMIN_PASSWORD, GOOGLE_MAPS_KEY  (all optional but recommended)
"""
import hmac
import os
import secrets
import sqlite3
from functools import wraps

from flask import (Flask, Response, abort, flash, g, redirect,
                   render_template, request, session, url_for)
from jinja2 import DictLoader
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("DB_PATH", os.path.join(BASE_DIR, "bloodconnect.db"))
BLOOD_GROUPS = ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"]
URGENCY_LEVELS = ["Emergency", "High", "Normal"]
ADMIN_STATUSES = {"Approved", "Rejected", "Completed"}

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")


# ---------------------------------------------------------------- database
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'donor'
        );
        CREATE TABLE IF NOT EXISTS donors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            blood_group TEXT NOT NULL,
            phone TEXT NOT NULL,
            city TEXT NOT NULL,
            availability TEXT NOT NULL DEFAULT 'Available',
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS blood_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            requester_name TEXT NOT NULL,
            phone TEXT NOT NULL,
            blood_group TEXT NOT NULL,
            units INTEGER NOT NULL,
            hospital TEXT NOT NULL,
            city TEXT NOT NULL,
            urgency TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Pending'
        );
    """)
    if not db.execute("SELECT 1 FROM users WHERE role='admin'").fetchone():
        email = os.environ.get("ADMIN_EMAIL", "admin@bloodconnect.com")
        pwd = os.environ.get("ADMIN_PASSWORD")
        if not pwd:
            pwd = secrets.token_urlsafe(9)
            print(f"[BloodConnect] Admin created -> {email} / {pwd} "
                  "(set ADMIN_PASSWORD env var to choose your own)", flush=True)
        db.execute("INSERT INTO users (name, email, password, role) VALUES (?,?,?,'admin')",
                   ("Admin", email.lower(), generate_password_hash(pwd)))
    db.commit()
    db.close()


# ----------------------------------------------------------------- helpers
def verify_password(stored, given):
    """Works with hashed passwords and with old plain-text ones."""
    if stored.startswith(("pbkdf2:", "scrypt:")):
        return check_password_hash(stored, given)
    return hmac.compare_digest(stored.encode(), given.encode())


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            flash("Please login first.", "error")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


def admin_required(f):
    @wraps(f)
    @login_required
    def wrapper(*args, **kwargs):
        if session.get("role") != "admin":
            abort(403)
        return f(*args, **kwargs)
    return wrapper


@app.context_processor
def inject_globals():
    return {"maps_key": os.environ.get("GOOGLE_MAPS_KEY", "")}


# ------------------------------------------------------------------ routes
@app.route("/")
def home():
    db = get_db()
    donors = db.execute(
        "SELECT u.name, d.city, d.blood_group FROM donors d JOIN users u ON u.id = d.user_id "
        "WHERE d.availability = 'Available' ORDER BY d.id DESC LIMIT 6").fetchall()
    requests_ = db.execute(
        "SELECT * FROM blood_requests WHERE status != 'Rejected' ORDER BY id DESC LIMIT 5").fetchall()
    return render_template("index.html", donors=donors, requests=requests_)


@app.route("/search")
def search():
    blood = request.args.get("blood_group", "").strip()
    city = request.args.get("city", "").strip()
    sql = ("SELECT u.name, d.phone, d.city, d.blood_group FROM donors d "
           "JOIN users u ON u.id = d.user_id WHERE d.availability = 'Available'")
    params = []
    if blood in BLOOD_GROUPS:
        sql += " AND d.blood_group = ?"
        params.append(blood)
    if city:
        sql += " AND lower(d.city) LIKE ?"
        params.append(f"%{city.lower()}%")
    donors = get_db().execute(sql + " ORDER BY d.id DESC", params).fetchall()
    return render_template("search.html", donors=donors, blood=blood, city=city)


@app.route("/request", methods=["GET", "POST"])
def request_blood():
    if request.method == "POST":
        f = request.form
        name, phone = f.get("requester_name", "").strip(), f.get("phone", "").strip()
        blood, hospital = f.get("blood_group", ""), f.get("hospital", "").strip()
        city, urgency = f.get("city", "").strip(), f.get("urgency", "Normal")
        try:
            units = int(f.get("units", "0"))
        except ValueError:
            units = 0
        if (not all([name, phone, hospital, city]) or blood not in BLOOD_GROUPS
                or urgency not in URGENCY_LEVELS or not 1 <= units <= 20):
            flash("Please fill all fields correctly.", "error")
            return render_template("request.html")
        db = get_db()
        db.execute("INSERT INTO blood_requests (requester_name, phone, blood_group, units, "
                   "hospital, city, urgency) VALUES (?,?,?,?,?,?,?)",
                   (name, phone, blood, units, hospital, city, urgency))
        db.commit()
        flash("Blood request submitted successfully.", "success")
        return redirect(url_for("home"))
    return render_template("request.html")


@app.route("/request/<int:req_id>")
def request_details(req_id):
    row = get_db().execute("SELECT * FROM blood_requests WHERE id = ?", (req_id,)).fetchone()
    if row is None:
        abort(404)
    return render_template("request_details.html", r=row)


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        f = request.form
        name, email = f.get("name", "").strip(), f.get("email", "").strip().lower()
        password, blood = f.get("password", ""), f.get("blood_group", "")
        phone, city = f.get("phone", "").strip(), f.get("city", "").strip()
        if not all([name, email, phone, city]) or blood not in BLOOD_GROUPS or len(password) < 6:
            flash("Fill all fields correctly (password needs at least 6 characters).", "error")
            return render_template("register.html")
        db = get_db()
        try:
            cur = db.execute("INSERT INTO users (name, email, password, role) VALUES (?,?,?,'donor')",
                             (name, email, generate_password_hash(password)))
            db.execute("INSERT INTO donors (user_id, blood_group, phone, city) VALUES (?,?,?,?)",
                       (cur.lastrowid, blood, phone, city))
            db.commit()
        except sqlite3.IntegrityError:
            db.rollback()
            flash("That email is already registered.", "error")
            return render_template("register.html")
        flash("Registration successful. Please login.", "success")
        return redirect(url_for("login"))
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        chosen_role = request.form.get("role", "user")
        db = get_db()
        user = db.execute("SELECT * FROM users WHERE lower(email) = ?", (email,)).fetchone()
        if user is None or not verify_password(user["password"], password):
            flash("Invalid email or password.", "error")
            return render_template("login.html")
        is_admin = user["role"] == "admin"
        if (chosen_role == "admin") != is_admin:
            flash("The selected login type does not match this account.", "error")
            return render_template("login.html")
        if not user["password"].startswith(("pbkdf2:", "scrypt:")):  # upgrade old plain-text password
            db.execute("UPDATE users SET password = ? WHERE id = ?",
                       (generate_password_hash(password), user["id"]))
            db.commit()
        session.clear()
        session["user_id"], session["role"], session["name"] = user["id"], user["role"], user["name"]
        flash(f"Welcome, {user['name']}!", "success")
        return redirect(url_for("admin" if is_admin else "profile"))
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out.", "success")
    return redirect(url_for("home"))


@app.route("/profile")
@login_required
def profile():
    donor = get_db().execute(
        "SELECT u.name, u.email, d.phone, d.blood_group, d.city, d.availability "
        "FROM users u JOIN donors d ON d.user_id = u.id WHERE u.id = ?",
        (session["user_id"],)).fetchone()
    if donor is None:
        flash("No donor profile found for this account.", "error")
        return redirect(url_for("admin" if session.get("role") == "admin" else "home"))
    return render_template("profile.html", donor=donor)


@app.route("/profile/availability", methods=["POST"])
@login_required
def toggle_availability():
    db = get_db()
    db.execute("UPDATE donors SET availability = CASE availability WHEN 'Available' "
               "THEN 'Not Available' ELSE 'Available' END WHERE user_id = ?", (session["user_id"],))
    db.commit()
    return redirect(url_for("profile"))


@app.route("/admin")
@admin_required
def admin():
    db = get_db()
    one = lambda sql: db.execute(sql).fetchone()[0]
    stats = {
        "donors": one("SELECT COUNT(*) FROM donors"),
        "available": one("SELECT COUNT(*) FROM donors WHERE availability = 'Available'"),
        "requests": one("SELECT COUNT(*) FROM blood_requests"),
        "pending": one("SELECT COUNT(*) FROM blood_requests WHERE status = 'Pending'"),
    }
    requests_ = db.execute("SELECT * FROM blood_requests ORDER BY id DESC").fetchall()
    donors = db.execute(
        "SELECT u.name, d.blood_group, d.phone, d.city, d.availability FROM donors d "
        "JOIN users u ON u.id = d.user_id ORDER BY d.id DESC").fetchall()
    return render_template("admin.html", stats=stats, requests=requests_, donors=donors)


@app.route("/admin/request/<int:req_id>/<status>")
@admin_required
def update_request(req_id, status):
    if status not in ADMIN_STATUSES:
        abort(400)
    db = get_db()
    db.execute("UPDATE blood_requests SET status = ? WHERE id = ?", (status, req_id))
    db.commit()
    flash(f"Request #{req_id} marked as {status}.", "success")
    return redirect(url_for("admin"))


@app.route("/style.css")
def style_css():
    return Response(CSS, mimetype="text/css")


@app.route("/app.js")
def app_js():
    return Response(JS, mimetype="application/javascript")


# --------------------------------------------------------------- templates
TEMPLATES = {

"base.html": r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>BloodConnect</title>
<link rel="stylesheet" href="{{ url_for('style_css') }}">
</head>
<body>
<nav>
  <a class="brand" href="{{ url_for('home') }}">🩸 BloodConnect</a>
  <div class="navlinks">
    <a href="{{ url_for('home') }}">Home</a>
    <a href="{{ url_for('search') }}">Find Donor</a>
    <a href="{{ url_for('request_blood') }}">Blood Request</a>
    {% if session.get('user_id') %}
      <a href="{{ url_for('profile') }}">Profile</a>
      {% if session.get('role') == 'admin' %}<a href="{{ url_for('admin') }}">Admin</a>{% endif %}
      <a href="{{ url_for('logout') }}">Logout</a>
    {% else %}
      <a href="{{ url_for('login') }}">Login</a>
      <a class="navbtn" href="{{ url_for('register') }}">Become a Donor</a>
    {% endif %}
  </div>
</nav>
{% with messages = get_flashed_messages(with_categories=true) %}
  {% if messages %}
    <div class="flash-wrap">
    {% for category, message in messages %}<div class="flash {{ category }}">{{ message }}</div>{% endfor %}
    </div>
  {% endif %}
{% endwith %}
<main>{% block content %}{% endblock %}</main>
<footer>© 2026 BloodConnect • Donate Blood • Save Lives</footer>
<script src="{{ url_for('app_js') }}"></script>
{% if maps_key %}<script async defer src="https://maps.googleapis.com/maps/api/js?key={{ maps_key }}&callback=initGoogleMaps"></script>{% endif %}
</body>
</html>
""",

"index.html": r"""{% extends "base.html" %}
{% block content %}
<section class="hero">
  <div>
    <span class="badge">Emergency Blood Support</span>
    <h1>Every drop of blood can <span>save a life.</span></h1>
    <p>BloodConnect helps patients find available blood donors quickly based on blood group and location.</p>
    <div class="actions">
      <a class="btn" href="{{ url_for('search') }}">Find a Donor</a>
      <a class="btn outline" href="{{ url_for('request_blood') }}">Request Blood</a>
    </div>
  </div>
  <div class="hero-card">
    <div class="bigdrop">🩸</div>
    <h3>Be someone's reason to smile.</h3>
    <p>Register as a donor and keep your availability updated.</p>
    <a href="{{ url_for('register') }}">Register now →</a>
  </div>
</section>

<section class="section">
<h2>Available Donors</h2><p class="muted">Recently registered donors who are currently available.</p>
<div class="grid">
{% for d in donors %}
<div class="card donor-card">
  <div class="avatar">👤</div>
  <div><h3>{{ d.name }}</h3><p>{{ d.city }}</p></div>
  <strong class="blood">{{ d.blood_group }}</strong>
  <span class="status">● Available</span>
</div>
{% else %}<div class="empty">No donors available yet. Be the first donor!</div>{% endfor %}
</div>
</section>

<section class="section two">
<div>
<h2>Recent Blood Requests</h2>
{% for r in requests %}
<a class="request-link" href="{{ url_for('request_details', req_id=r.id) }}"><div class="request-row"><div><b>{{ r.blood_group }} • {{ r.units }} unit(s)</b><br><small>{{ r.hospital }}, {{ r.city }}</small></div><span class="tag {{ r.urgency|lower }}">{{ r.urgency }}</span></div></a>
{% else %}<p class="muted">No requests yet.</p>{% endfor %}
</div>
<div class="map-card"><h2>Blood Request Locations</h2><div id="map"></div><small class="muted">Recent requests are shown using their city locations.</small></div>
</section>
<script>window.bloodRequests = {{ requests|map(attribute='city')|list|tojson }};</script>
{% endblock %}
""",

"login.html": r"""{% extends "base.html" %}
{% block content %}
<div class="form-page"><form class="form-card" method="post">
<h1>Welcome back</h1><p class="muted">Login to manage your donor profile.</p>
<label>Login as
<select name="role" required>
<option value="user">User</option>
<option value="admin">Admin</option>
</select>
</label>
<label>Email<input type="email" name="email" required></label>
<label>Password<input type="password" name="password" required></label>
<button class="btn full">Login</button>
<p class="center">New donor? <a href="{{ url_for('register') }}">Register</a></p>
</form></div>
{% endblock %}
""",

"register.html": r"""{% extends "base.html" %}
{% block content %}
<div class="form-page"><form class="form-card" method="post">
<h1>Become a Blood Donor</h1><p class="muted">Create your BloodConnect donor account.</p>
<label>Full Name<input name="name" required></label>
<label>Email<input type="email" name="email" required></label>
<label>Password<input type="password" name="password" minlength="6" required></label>
<div class="form-grid">
<label>Blood Group<select name="blood_group" required><option value="">Select</option>{% for g in ['A+','A-','B+','B-','AB+','AB-','O+','O-'] %}<option>{{g}}</option>{% endfor %}</select></label>
<label>Phone<input name="phone" required></label>
</div>
<label>City / Location<input name="city" placeholder="e.g. Chennai" required></label>
<button class="btn full">Register</button>
<p class="center">Already registered? <a href="{{ url_for('login') }}">Login</a></p>
</form></div>
{% endblock %}
""",

"profile.html": r"""{% extends "base.html" %}
{% block content %}
<section class="section profile">
<h1>Hello, {{ donor.name }} 👋</h1><p class="muted">Your donor profile</p>
<div class="profile-grid">
<div class="card"><h3>Donor Details</h3><p><b>Email:</b> {{ donor.email }}</p><p><b>Phone:</b> {{ donor.phone }}</p><p><b>Blood Group:</b> <span class="blood">{{ donor.blood_group }}</span></p><p><b>Location:</b> {{ donor.city }}</p></div>
<div class="card"><h3>Availability</h3><div class="availability">{{ donor.availability }}</div><form method="post" action="{{ url_for('toggle_availability') }}"><button class="btn">{{ 'Mark Not Available' if donor.availability == 'Available' else 'Mark Available' }}</button></form></div>
</div>
</section>
{% endblock %}
""",

"search.html": r"""{% extends "base.html" %}
{% block content %}
<section class="section">
<h1>Find a Blood Donor</h1><p class="muted">Search available donors by blood group and city.</p>
<form class="searchbar" method="get">
<select name="blood_group"><option value="">All Blood Groups</option>{% for g in ['A+','A-','B+','B-','AB+','AB-','O+','O-'] %}<option {% if blood==g %}selected{% endif %}>{{g}}</option>{% endfor %}</select>
<input name="city" value="{{ city }}" placeholder="City / Location">
<button class="btn">Search</button>
</form>
<div class="grid">
{% for d in donors %}
<div class="card donor-card">
<div class="avatar">🩸</div><div><h3>{{ d.name }}</h3><p>{{ d.city }}</p><p>📞 {{ d.phone }}</p></div>
<strong class="blood">{{ d.blood_group }}</strong><span class="status">● Available</span>
</div>
{% else %}<div class="empty">No matching available donors found.</div>{% endfor %}
</div>
</section>
{% endblock %}
""",

"request.html": r"""{% extends "base.html" %}
{% block content %}
<div class="form-page"><form class="form-card" method="post">
<h1>Emergency Blood Request</h1><p class="muted">Submit a request so matching donors can be identified.</p>
<div class="form-grid">
<label>Requester Name<input name="requester_name" required></label>
<label>Phone<input name="phone" required></label>
</div>
<div class="form-grid">
<label>Blood Group<select name="blood_group" required><option value="">Select</option>{% for g in ['A+','A-','B+','B-','AB+','AB-','O+','O-'] %}<option>{{g}}</option>{% endfor %}</select></label>
<label>Units Required<input type="number" name="units" min="1" max="20" required></label>
</div>
<label>Hospital / Medical Center<input name="hospital" required></label>
<label>City / Location<input name="city" required></label>
<label>Urgency<select name="urgency"><option>Emergency</option><option>High</option><option>Normal</option></select></label>
<button class="btn full">Submit Blood Request</button>
</form></div>
{% endblock %}
""",

"request_details.html": r"""{% extends "base.html" %}{% block content %}<section class="section"><a href="{{ url_for('home') }}">← Back</a><div class="details-grid"><div class="card"><span class="badge">Blood Request #{{ r.id }}</span><h1>{{ r.blood_group }} Blood Required</h1><p class="muted">Requester details</p><div class="detail-list"><p><b>Requester</b><span>{{ r.requester_name }}</span></p><p><b>Phone</b><span>{{ r.phone }}</span></p><p><b>Blood Group</b><span class="blood">{{ r.blood_group }}</span></p><p><b>Units</b><span>{{ r.units }}</span></p><p><b>Hospital</b><span>{{ r.hospital }}</span></p><p><b>Location</b><span>{{ r.city }}</span></p><p><b>Urgency</b><span>{{ r.urgency }}</span></p><p><b>Status</b><span>{{ r.status }}</span></p></div><a class="btn" href="tel:{{ r.phone }}">📞 Contact Requester</a></div><div class="map-card"><h2>📍 Requester Location</h2><p class="muted">Google Maps</p><div id="requester-map"></div></div></div></section><script>window.addEventListener("load",function(){showGoogleMapForLocation("requester-map",{{ r.city|tojson }},"Blood Requester");});</script>{% endblock %}
""",

"admin.html": r"""{% extends "base.html" %}
{% block content %}
<section class="section">
<h1>Admin Dashboard</h1><p class="muted">Manage donors and blood requests.</p>
<div class="stats">
<div class="stat"><b>{{stats.donors}}</b><span>Total Donors</span></div>
<div class="stat"><b>{{stats.available}}</b><span>Available</span></div>
<div class="stat"><b>{{stats.requests}}</b><span>Requests</span></div>
<div class="stat"><b>{{stats.pending}}</b><span>Pending</span></div>
</div>
<div class="table-card"><h2>Blood Requests</h2><div class="table-scroll"><table><tr><th>ID</th><th>Requester</th><th>Blood</th><th>Hospital</th><th>City</th><th>Urgency</th><th>Status</th><th>Action</th></tr>
{% for r in requests %}<tr><td>#{{r.id}}</td><td>{{r.requester_name}}</td><td><b>{{r.blood_group}}</b></td><td>{{r.hospital}}</td><td>{{r.city}}</td><td>{{r.urgency}}</td><td>{{r.status}}</td><td>{% if r.status == 'Pending' %}<a href="{{url_for('update_request',req_id=r.id,status='Approved')}}">Approve</a> | <a href="{{url_for('update_request',req_id=r.id,status='Rejected')}}">Reject</a>{% elif r.status == 'Approved' %}<a href="{{url_for('update_request',req_id=r.id,status='Completed')}}">Complete</a>{% else %}—{% endif %}</td></tr>{% endfor %}
</table></div></div>
<div class="table-card"><h2>Donors</h2><div class="table-scroll"><table><tr><th>Name</th><th>Blood</th><th>Phone</th><th>City</th><th>Availability</th></tr>
{% for d in donors %}<tr><td>{{d.name}}</td><td><b>{{d.blood_group}}</b></td><td>{{d.phone}}</td><td>{{d.city}}</td><td>{{d.availability}}</td></tr>{% endfor %}
</table></div></div>
</section>
{% endblock %}
""",
}


# --------------------------------------------------------------------- CSS
CSS = r"""
:root{--red:#c62828;--dark:#8e1b1b;--bg:#fff7f7;--ink:#2b1d1d;--muted:#7a6a6a;--line:#f0dcdc}
*{box-sizing:border-box}
body{margin:0;font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;background:var(--bg);color:var(--ink);line-height:1.5}
a{color:var(--red)}
nav{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;padding:14px 5%;background:#fff;border-bottom:1px solid var(--line);position:sticky;top:0;z-index:10}
.brand{font-weight:800;font-size:1.25rem;text-decoration:none;color:var(--red)}
.navlinks{display:flex;gap:16px;align-items:center;flex-wrap:wrap}
.navlinks a{text-decoration:none;color:var(--ink);font-weight:500}
.navlinks a:hover{color:var(--red)}
.navlinks .navbtn{background:var(--red);color:#fff;padding:8px 16px;border-radius:999px}
.navlinks .navbtn:hover{background:var(--dark);color:#fff}
main{min-height:70vh}
footer{text-align:center;padding:24px;color:var(--muted);border-top:1px solid var(--line);background:#fff}
.flash-wrap{padding:12px 5% 0}
.flash{padding:12px 16px;border-radius:10px;margin-bottom:8px;background:#e8f5e9;color:#1b5e20}
.flash.error,.flash.danger{background:#ffebee;color:#b71c1c}
.section{padding:36px 5%}
.hero{display:grid;grid-template-columns:1.4fr 1fr;gap:32px;align-items:center;padding:56px 5%;background:linear-gradient(135deg,#fff,#ffe9e9)}
.hero h1{font-size:clamp(2rem,5vw,3.4rem);line-height:1.1;margin:14px 0}
.hero h1 span{color:var(--red)}
.badge{display:inline-block;background:#ffe0e0;color:var(--dark);padding:5px 12px;border-radius:999px;font-size:.85rem;font-weight:600}
.actions{display:flex;gap:12px;flex-wrap:wrap;margin-top:20px}
.btn{display:inline-block;background:var(--red);color:#fff;border:2px solid var(--red);padding:11px 22px;border-radius:10px;font-weight:600;text-decoration:none;cursor:pointer;font-size:1rem;font-family:inherit}
.btn:hover{background:var(--dark);border-color:var(--dark)}
.btn.outline{background:transparent;color:var(--red)}
.btn.outline:hover{background:var(--red);color:#fff}
.btn.full{width:100%;margin-top:14px}
.hero-card,.card,.form-card,.map-card,.table-card,.stat{background:#fff;border:1px solid var(--line);border-radius:16px;padding:22px;box-shadow:0 6px 20px rgba(198,40,40,.06)}
.hero-card{text-align:center}
.bigdrop{font-size:4rem}
.muted{color:var(--muted)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:16px;margin-top:16px}
.donor-card{display:grid;grid-template-columns:auto 1fr auto;gap:6px 14px;align-items:center}
.donor-card h3,.donor-card p{margin:0}
.avatar{font-size:2rem}
.blood{color:var(--red);font-weight:800;font-size:1.2rem}
.status{grid-column:1/-1;color:#2e7d32;font-size:.85rem}
.empty{grid-column:1/-1;padding:24px;text-align:center;color:var(--muted);background:#fff;border:1px dashed var(--line);border-radius:12px}
.two{display:grid;grid-template-columns:1fr 1fr;gap:24px}
.request-link{text-decoration:none;color:inherit}
.request-row{display:flex;justify-content:space-between;align-items:center;gap:10px;background:#fff;border:1px solid var(--line);border-radius:12px;padding:14px 16px;margin-bottom:10px}
.request-row:hover{border-color:var(--red)}
.tag{padding:4px 12px;border-radius:999px;font-size:.8rem;font-weight:700;background:#eee}
.tag.emergency{background:#ffebee;color:#b71c1c}
.tag.high{background:#fff3e0;color:#e65100}
.tag.normal{background:#e8f5e9;color:#1b5e20}
#map,#requester-map{height:320px;border-radius:12px;background:#f3e5e5;margin:12px 0}
.form-page{display:flex;justify-content:center;padding:40px 5%}
.form-card{width:100%;max-width:520px}
label{display:block;font-weight:600;margin:12px 0 0;font-size:.92rem}
input,select{width:100%;padding:11px 12px;margin-top:6px;border:1px solid #e0cccc;border-radius:10px;font-size:1rem;font-family:inherit;background:#fff}
input:focus,select:focus{outline:2px solid #f3b4b4;border-color:var(--red)}
.form-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.center{text-align:center}
.searchbar{display:grid;grid-template-columns:1fr 1fr auto;gap:10px;margin:18px 0;max-width:720px}
.searchbar select,.searchbar input{margin-top:0}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:14px;margin:18px 0}
.stat b{display:block;font-size:2rem;color:var(--red)}
.table-card{margin-top:20px}
.table-scroll{overflow-x:auto}
table{width:100%;border-collapse:collapse;min-width:620px}
th,td{padding:10px 12px;text-align:left;border-bottom:1px solid var(--line);font-size:.92rem}
th{background:#fff3f3}
.profile-grid,.details-grid{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-top:16px}
.availability{font-size:1.6rem;font-weight:800;color:#2e7d32;margin:10px 0}
.detail-list p{display:flex;justify-content:space-between;gap:12px;margin:0;padding:9px 0;border-bottom:1px solid var(--line)}
@media(max-width:800px){.hero,.two,.profile-grid,.details-grid{grid-template-columns:1fr}.searchbar{grid-template-columns:1fr}}
"""


# ---------------------------------------------------------------------- JS
JS = r"""
var mapQueue = [];
var DEFAULT_CENTER = { lat: 11.1271, lng: 78.6569 };

function mapsReady() {
  return window.google && google.maps && google.maps.Map;
}

function placeCity(map, city, title, recenter) {
  new google.maps.Geocoder().geocode({ address: city, region: "IN" }, function (res, status) {
    if (status === "OK" && res[0]) {
      if (recenter) { map.setCenter(res[0].geometry.location); }
      new google.maps.Marker({ map: map, position: res[0].geometry.location, title: title });
    }
  });
}

function showGoogleMapForLocation(elId, city, title) {
  if (!mapsReady()) { mapQueue.push([elId, city, title]); return; }
  var el = document.getElementById(elId);
  if (!el || !city) { return; }
  var map = new google.maps.Map(el, { zoom: 11, center: DEFAULT_CENTER });
  placeCity(map, city, title, true);
}

function initGoogleMaps() {
  mapQueue.forEach(function (q) { showGoogleMapForLocation(q[0], q[1], q[2]); });
  mapQueue = [];
  var el = document.getElementById("map");
  if (!el) { return; }
  var map = new google.maps.Map(el, { zoom: 6, center: DEFAULT_CENTER });
  var seen = {};
  (window.bloodRequests || []).forEach(function (city) {
    if (city && !seen[city]) { seen[city] = true; placeCity(map, city, city, false); }
  });
}
"""


# -------------------------------------------------------------------- boot
app.jinja_loader = DictLoader(TEMPLATES)
init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
