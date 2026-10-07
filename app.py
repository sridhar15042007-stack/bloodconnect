from flask import Flask, jsonify, request, session, send_from_directory
import sqlite3
import os

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "bloodconnect.db")

BLOOD_GROUPS = ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"]
URGENCIES = ["Emergency", "High", "Normal"]
ADMIN_STATUSES = ["Approved", "Completed", "Rejected"]

# index.html, style.css and script.js sit next to this file and are served by the
# routes below (logos are inside index.html). No static folder, so app.py and the
# .db can never be downloaded.
app = Flask(__name__, static_folder=None)
app.secret_key = os.environ.get("SECRET_KEY", "bloodconnect-secret-key")


# ---------------------------------------------------------------- database
def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
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
    conn.execute("""INSERT INTO users(name, email, password, role)
                    VALUES(?,?,?,'admin')
                    ON CONFLICT(email) DO UPDATE SET role='admin'""",
                 ("Administrator", "admin@bloodconnect.com", "admin123"))
    conn.commit()
    conn.close()


init_db()


def query(sql, params=()):
    """Run a SELECT and return a list of dicts."""
    conn = get_db()
    try:
        return [dict(row) for row in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


# ---------------------------------------------------------------- helpers
def fail(message, status=400):
    return jsonify(error=message), status


def current_user():
    if "user_id" not in session:
        return None
    return {"id": session["user_id"], "name": session["name"], "role": session["role"]}


def is_admin():
    return session.get("role") == "admin"


# ---------------------------------------------------------------- front-end files
@app.route("/")
def index():
    return send_from_directory(BASE, "index.html")


@app.route("/<any(style.css,script.js):filename>")
def front_files(filename):
    return send_from_directory(BASE, filename)


# ---------------------------------------------------------------- JSON API
@app.get("/api/me")
def api_me():
    return jsonify(user=current_user())


@app.get("/api/home")
def api_home():
    donors = query("""
        SELECT donors.id, users.name, donors.blood_group, donors.city
        FROM donors JOIN users ON donors.user_id = users.id
        WHERE donors.availability='Available'
        ORDER BY donors.id DESC LIMIT 6
    """)
    requests_ = query("""
        SELECT id, blood_group, units, hospital, city, urgency
        FROM blood_requests ORDER BY id DESC LIMIT 5
    """)
    return jsonify(donors=donors, requests=requests_)


@app.post("/api/register")
def api_register():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip()
    password = data.get("password") or ""
    blood_group = data.get("blood_group") or ""
    phone = (data.get("phone") or "").strip()
    city = (data.get("city") or "").strip()

    if not all([name, email, password, blood_group, phone, city]):
        return fail("All fields are required.")
    if blood_group not in BLOOD_GROUPS:
        return fail("Invalid blood group.")

    conn = get_db()
    try:
        cur = conn.execute("INSERT INTO users(name,email,password) VALUES(?,?,?)",
                           (name, email, password))
        conn.execute("""INSERT INTO donors(user_id,blood_group,phone,city)
                        VALUES(?,?,?,?)""", (cur.lastrowid, blood_group, phone, city))
        conn.commit()
    except sqlite3.IntegrityError:
        return fail("Email already registered.", 409)
    finally:
        conn.close()
    return jsonify(ok=True), 201


@app.post("/api/login")
def api_login():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip()
    password = data.get("password") or ""
    selected_role = data.get("role") or "user"

    users = query("SELECT * FROM users WHERE email=? AND password=?", (email, password))
    user = users[0] if users else None
    actual_role = "admin" if user and user["role"] == "admin" else "user"

    if user and selected_role == actual_role:
        session["user_id"] = user["id"]
        session["name"] = user["name"]
        session["role"] = user["role"]
        return jsonify(user=current_user())
    return fail("Invalid email, password, or login type.", 401)


@app.post("/api/logout")
def api_logout():
    session.clear()
    return jsonify(ok=True)


@app.get("/api/profile")
def api_profile():
    if "user_id" not in session:
        return fail("Please login.", 401)
    rows = query("""
        SELECT users.name, users.email, donors.blood_group, donors.phone,
               donors.city, donors.availability
        FROM users LEFT JOIN donors ON donors.user_id = users.id
        WHERE users.id=?""", (session["user_id"],))
    if not rows:
        session.clear()
        return fail("Please login.", 401)
    row = rows[0]
    donor = row if row["blood_group"] is not None else None   # admin has no donor row
    return jsonify(user={"name": row["name"], "email": row["email"], "role": session["role"]},
                   donor=donor)


@app.post("/api/toggle-availability")
def api_toggle_availability():
    if "user_id" not in session:
        return fail("Please login.", 401)
    conn = get_db()
    try:
        donor = conn.execute("SELECT availability FROM donors WHERE user_id=?",
                             (session["user_id"],)).fetchone()
        if not donor:
            return fail("This account has no donor profile.", 404)
        new_status = "Not Available" if donor["availability"] == "Available" else "Available"
        conn.execute("UPDATE donors SET availability=? WHERE user_id=?",
                     (new_status, session["user_id"]))
        conn.commit()
    finally:
        conn.close()
    return jsonify(availability=new_status)


@app.get("/api/search")
def api_search():
    blood = request.args.get("blood_group", "").strip()
    city = request.args.get("city", "").strip()
    sql = """SELECT donors.id, users.name, donors.blood_group, donors.city, donors.phone
             FROM donors JOIN users ON donors.user_id=users.id
             WHERE donors.availability='Available'"""
    params = []
    if blood:
        sql += " AND donors.blood_group=?"
        params.append(blood)
    if city:
        sql += " AND donors.city LIKE ?"
        params.append("%" + city + "%")
    return jsonify(donors=query(sql + " ORDER BY donors.id DESC", params))


@app.post("/api/request-blood")
def api_request_blood():
    data = request.get_json(silent=True) or {}
    requester_name = (data.get("requester_name") or "").strip()
    phone = (data.get("phone") or "").strip()
    blood_group = data.get("blood_group") or ""
    hospital = (data.get("hospital") or "").strip()
    city = (data.get("city") or "").strip()
    urgency = data.get("urgency") or "Emergency"
    try:
        units = int(data.get("units"))
    except (TypeError, ValueError):
        return fail("Units must be a number.")

    if not all([requester_name, phone, hospital, city]):
        return fail("All fields are required.")
    if blood_group not in BLOOD_GROUPS:
        return fail("Invalid blood group.")
    if urgency not in URGENCIES:
        return fail("Invalid urgency.")
    if not 1 <= units <= 20:
        return fail("Units must be between 1 and 20.")

    conn = get_db()
    try:
        conn.execute("""INSERT INTO blood_requests
                        (requester_name,phone,blood_group,units,hospital,city,urgency)
                        VALUES(?,?,?,?,?,?,?)""",
                     (requester_name, phone, blood_group, units, hospital, city, urgency))
        conn.commit()
    finally:
        conn.close()
    return jsonify(ok=True), 201


@app.get("/api/request/<int:req_id>")
def api_request_details(req_id):
    rows = query("SELECT * FROM blood_requests WHERE id=?", (req_id,))
    if not rows:
        return fail("Blood request not found.", 404)
    return jsonify(request=rows[0])


@app.get("/api/admin")
def api_admin():
    if not is_admin():
        return fail("Admin access only.", 403)
    count = lambda sql: query(sql)[0]["n"]
    stats = {
        "donors": count("SELECT COUNT(*) AS n FROM donors"),
        "available": count("SELECT COUNT(*) AS n FROM donors WHERE availability='Available'"),
        "requests": count("SELECT COUNT(*) AS n FROM blood_requests"),
        "pending": count("SELECT COUNT(*) AS n FROM blood_requests WHERE status='Pending'"),
    }
    donors = query("""SELECT donors.id, users.name, donors.blood_group, donors.phone,
                             donors.city, donors.availability
                      FROM donors JOIN users ON donors.user_id=users.id
                      ORDER BY donors.id DESC""")
    requests_ = query("SELECT * FROM blood_requests ORDER BY id DESC")
    return jsonify(stats=stats, donors=donors, requests=requests_)


@app.post("/api/admin/request/<int:req_id>/<status>")
def api_update_request(req_id, status):
    if not is_admin():
        return fail("Admin access only.", 403)
    if status not in ADMIN_STATUSES:
        return fail("Invalid status.")
    conn = get_db()
    try:
        cur = conn.execute("UPDATE blood_requests SET status=? WHERE id=?", (status, req_id))
        conn.commit()
    finally:
        conn.close()
    if cur.rowcount == 0:
        return fail("Blood request not found.", 404)
    return jsonify(ok=True)


if __name__ == "__main__":
    app.run(debug=True)
