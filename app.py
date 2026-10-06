from flask import Flask, render_template, request, redirect, url_for, session, flash
import sqlite3, os

app = Flask(__name__, template_folder='.')
app.secret_key = "bloodconnect-secret-key"
DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bloodconnect.db")

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

@app.route("/")
def home():
    conn = get_db()
    donors = conn.execute("""
        SELECT donors.*, users.name FROM donors
        JOIN users ON donors.user_id = users.id
        WHERE availability='Available'
        ORDER BY donors.id DESC LIMIT 6
    """).fetchall()
    requests = conn.execute("""
        SELECT * FROM blood_requests ORDER BY id DESC LIMIT 5
    """).fetchall()
    conn.close()
    return render_template("index.html", donors=donors, requests=requests)

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form["name"].strip()
        email = request.form["email"].strip()
        password = request.form["password"]
        blood_group = request.form["blood_group"]
        phone = request.form["phone"].strip()
        city = request.form["city"].strip()
        try:
            conn = get_db()
            cur = conn.execute("INSERT INTO users(name,email,password) VALUES(?,?,?)",
                               (name,email,password))
            user_id = cur.lastrowid
            conn.execute("""INSERT INTO donors(user_id,blood_group,phone,city)
                            VALUES(?,?,?,?)""",
                         (user_id,blood_group,phone,city))
            conn.commit()
            conn.close()
            flash("Registration successful. Please login.", "success")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("Email already registered.", "error")
    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"].strip()
        password = request.form["password"]
        selected_role = request.form.get("role", "user")
        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE email=? AND password=?",
                            (email,password)).fetchone()
        conn.close()
        actual_role = "admin" if user and user["role"] == "admin" else "user"
        if user and selected_role == actual_role:
            session["user_id"] = user["id"]
            session["name"] = user["name"]
            session["role"] = user["role"]
            return redirect(url_for("admin" if user["role"] == "admin" else "profile"))
        flash("Invalid email, password, or login type.", "error")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))

@app.route("/profile")
def profile():
    if "user_id" not in session:
        return redirect(url_for("login"))
    conn = get_db()
    donor = conn.execute("""SELECT donors.*, users.name, users.email
                            FROM donors JOIN users ON donors.user_id=users.id
                            WHERE users.id=?""", (session["user_id"],)).fetchone()
    conn.close()
    return render_template("profile.html", donor=donor)

@app.route("/toggle-availability", methods=["POST"])
def toggle_availability():
    if "user_id" not in session:
        return redirect(url_for("login"))
    conn = get_db()
    donor = conn.execute("SELECT * FROM donors WHERE user_id=?", (session["user_id"],)).fetchone()
    new_status = "Not Available" if donor["availability"] == "Available" else "Available"
    conn.execute("UPDATE donors SET availability=? WHERE user_id=?", (new_status, session["user_id"]))
    conn.commit()
    conn.close()
    return redirect(url_for("profile"))

@app.route("/search")
def search():
    blood = request.args.get("blood_group","").strip()
    city = request.args.get("city","").strip()
    conn = get_db()
    query = """SELECT donors.*, users.name, users.email
               FROM donors JOIN users ON donors.user_id=users.id
               WHERE donors.availability='Available'"""
    params = []
    if blood:
        query += " AND donors.blood_group=?"
        params.append(blood)
    if city:
        query += " AND donors.city LIKE ?"
        params.append("%"+city+"%")
    donors = conn.execute(query + " ORDER BY donors.id DESC", params).fetchall()
    conn.close()
    return render_template("search.html", donors=donors, blood=blood, city=city)

@app.route("/request-blood", methods=["GET","POST"])
def request_blood():
    if request.method == "POST":
        conn = get_db()
        conn.execute("""INSERT INTO blood_requests
        (requester_name,phone,blood_group,units,hospital,city,urgency)
        VALUES(?,?,?,?,?,?,?)""",
        (request.form["requester_name"],request.form["phone"],
         request.form["blood_group"],request.form["units"],
         request.form["hospital"],request.form["city"],request.form["urgency"]))
        conn.commit()
        conn.close()
        flash("Blood request submitted successfully.", "success")
        return redirect(url_for("home"))
    return render_template("request.html")

@app.route("/request/<int:req_id>")
def request_details(req_id):
    conn=get_db(); r=conn.execute("SELECT * FROM blood_requests WHERE id=?",(req_id,)).fetchone(); conn.close()
    if not r: flash("Blood request not found.","error"); return redirect(url_for("home"))
    return render_template("request_details.html",r=r)

@app.route("/admin")
def admin():
    if session.get("role") != "admin":
        return redirect(url_for("login"))
    conn = get_db()
    stats = {
        "donors": conn.execute("SELECT COUNT(*) FROM donors").fetchone()[0],
        "available": conn.execute("SELECT COUNT(*) FROM donors WHERE availability='Available'").fetchone()[0],
        "requests": conn.execute("SELECT COUNT(*) FROM blood_requests").fetchone()[0],
        "pending": conn.execute("SELECT COUNT(*) FROM blood_requests WHERE status='Pending'").fetchone()[0]
    }
    donors = conn.execute("""SELECT donors.*, users.name, users.email
                             FROM donors JOIN users ON donors.user_id=users.id
                             ORDER BY donors.id DESC""").fetchall()
    requests = conn.execute("SELECT * FROM blood_requests ORDER BY id DESC").fetchall()
    conn.close()
    return render_template("admin.html", stats=stats, donors=donors, requests=requests)

@app.route("/admin/request/<int:req_id>/<status>")
def update_request(req_id, status):
    if session.get("role") != "admin" or status not in ["Approved","Completed","Rejected"]:
        return redirect(url_for("login"))
    conn = get_db()
    conn.execute("UPDATE blood_requests SET status=? WHERE id=?", (status,req_id))
    conn.commit()
    conn.close()
    return redirect(url_for("admin"))

if __name__ == "__main__":
    app.run(debug=True)
