import sqlite3, os, uuid
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, g, abort
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "galexy.db")
UPLOADS = os.path.join(BASE, "static", "uploads")
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret")
app.config["MAX_CONTENT_LENGTH"] = 15 * 1024 * 1024

CATEGORIES = ["Part Rack", "CAC / HAC", "Cage", "ODO", "Customize Solutions"]
SEED = [
 ("Part Rack", "Part Rack", "GS-PR-100", "Modular racks that keep parts and components organised, easy to find and quick to access on the shop floor.", "/static/products/part-rack.jpg"),
 ("CAC / HAC", "CAC Rack", "GS-CA-200", "Cold Aisle Containment seals the cold aisle so cool air reaches your equipment, improving cooling efficiency and cutting energy use.", "/static/products/cac.jpg"),
 ("CAC / HAC", "HAC Rack", "GS-HA-210", "Hot Aisle Containment captures hot exhaust air and sends it back to cooling, keeping the room temperature stable.", "/static/products/hac.jpg"),
 ("Cage", "Mesh Cage", "GS-CG-300", "Welded-mesh cage with open airflow and full visibility. Secure storage for equipment, parts and stock.", "/static/products/mesh-cage.jpg"),
 ("Cage", "Opac Cage", "GS-CG-310", "Opaque-panel cage that hides what is inside. Adds privacy and protection with a lockable door.", "/static/products/opac-cage.jpg"),
 ("ODO", "ODO", "GS-OD-400", "Outdoor enclosure built for rain, dust and sun. Protects electrical and network equipment in harsh conditions.", "/static/products/odo.jpg"),
 ("Customize Solutions", "Customize Solutions", "GS-CU-500", "Need a different size, finish or layout? Tell us your requirement and we build it to order.", "/static/products/custom.jpg"),
]
STATUSES = ["New", "Assigned", "In Progress", "Ready", "Dispatched"]

def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB); g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close(e=None):
    d = g.pop("db", None)
    if d: d.close()

def init():
    os.makedirs(UPLOADS, exist_ok=True)
    c = sqlite3.connect(DB)
    c.executescript("""
    CREATE TABLE IF NOT EXISTS admins(id INTEGER PRIMARY KEY, username TEXT UNIQUE, password TEXT);
    CREATE TABLE IF NOT EXISTS workers(id INTEGER PRIMARY KEY, name TEXT, phone TEXT, active INTEGER DEFAULT 1);
    CREATE TABLE IF NOT EXISTS products(id INTEGER PRIMARY KEY, category TEXT, name TEXT, code TEXT, summary TEXT, image TEXT, published INTEGER DEFAULT 1);
    CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY, customer TEXT, phone TEXT, email TEXT,
        product TEXT, quantity INTEGER, details TEXT, status TEXT DEFAULT 'New',
        worker_id INTEGER, created TEXT DEFAULT CURRENT_TIMESTAMP, dispatched TEXT);
    CREATE TABLE IF NOT EXISTS enquiries(id INTEGER PRIMARY KEY, name TEXT, phone TEXT, message TEXT,
        created TEXT DEFAULT CURRENT_TIMESTAMP);
    """)
    if not c.execute("SELECT 1 FROM admins").fetchone():
        c.execute("INSERT INTO admins(username,password) VALUES(?,?)", ("admin", generate_password_hash("admin123")))
    if not c.execute("SELECT 1 FROM products").fetchone():
        c.executemany("INSERT INTO products(category,name,code,summary,image) VALUES(?,?,?,?,?)", SEED)
    # keep names/images in sync with older databases (your own uploaded photos are never touched)
    c.execute("UPDATE products SET image=replace(replace(image,'/static/img/','/static/products/'),'.svg','.jpg') WHERE image LIKE '/static/img/%.svg'")
    for old, new in (("CAC - Cold Aisle Containment", "CAC Rack"), ("HAC - Hot Aisle Containment", "HAC Rack")):
        c.execute("UPDATE products SET name=? WHERE name=?", (new, old))
    for _cat, nm, _code, summ, _img in SEED:
        c.execute("UPDATE products SET summary=? WHERE name=? AND summary IN (SELECT summary FROM (SELECT 'Modular rack for organising parts and components.' summary UNION SELECT 'Contain cold air to improve cooling efficiency.' UNION SELECT 'Capture and channel hot exhaust air.' UNION SELECT 'Ventilated welded-mesh cage for secure storage.' UNION SELECT 'Opaque-panel cage for privacy and protection.' UNION SELECT 'Outdoor enclosure for harsh weather conditions.' UNION SELECT 'Tell us your size and use. We build it to order.'))", (summ, nm))
    c.commit(); c.close()

def login_required(f):
    @wraps(f)
    def w(*a, **k):
        if not session.get("admin"): return redirect(url_for("login"))
        return f(*a, **k)
    return w

def save_image():
    f = request.files.get("image_file")
    if f and f.filename:
        head = f.read(16); f.seek(0)
        if head.startswith(b"\xff\xd8\xff"): ext = ".jpg"
        elif head.startswith(b"\x89PNG"): ext = ".png"
        elif head[:4] == b"RIFF" and head[8:12] == b"WEBP": ext = ".webp"
        elif head[:6] in (b"GIF87a", b"GIF89a"): ext = ".gif"
        else: raise ValueError("That file is not a JPG, PNG, WEBP or GIF picture. If it is a phone photo (HEIC), convert it to JPG first.")
        name = uuid.uuid4().hex + ext
        f.save(os.path.join(UPLOADS, name)); return "/static/uploads/" + name
    return request.form.get("image_url", "").strip()

@app.errorhandler(413)
def too_big(e):
    flash("That image is too large (max 15 MB). Please make it smaller and try again.", "error")
    return redirect(request.referrer or url_for("dashboard"))

# ---------- public ----------
@app.context_processor
def inject(): return {"categories": CATEGORIES}

@app.route("/")
def home():
    rows = db().execute("SELECT * FROM products WHERE published=1 ORDER BY id").fetchall()
    return render_template("home.html", sliders=[(r["name"], r["summary"], r["image"]) for r in rows])

@app.route("/about")
def about(): return render_template("about.html")

@app.route("/products")
def products():
    rows = db().execute("SELECT * FROM products WHERE published=1 ORDER BY id").fetchall()
    cat = request.args.get("category")
    groups = {c: [r for r in rows if r["category"] == c] for c in CATEGORIES if not cat or c == cat}
    return render_template("products.html", groups=groups, current=cat)

@app.route("/order", methods=["GET", "POST"])
def order():
    plist = [dict(r) for r in db().execute("SELECT name,code,summary,image FROM products WHERE published=1 ORDER BY id")]
    names = [p["name"] for p in plist]
    if request.method == "POST":
        f = request.form
        try: qty = max(1, int(f.get("quantity", 1) or 1))
        except ValueError: qty = 1
        db().execute("INSERT INTO orders(customer,phone,email,product,quantity,details) VALUES(?,?,?,?,?,?)",
            (f["customer"], f["phone"], f.get("email", ""), f["product"], qty, f.get("details", "")))
        db().commit(); flash("Order received. We will contact you soon.")
        return redirect(url_for("order", product=f["product"]))
    sel = request.args.get("product", "")
    if sel not in names and names: sel = names[0]
    return render_template("order.html", products=plist, selected=sel)

@app.route("/contact", methods=["POST"])
def contact():
    db().execute("INSERT INTO enquiries(name,phone,message) VALUES(?,?,?)",
                 (request.form["name"], request.form["phone"], request.form["message"]))
    db().commit(); flash("Thanks, we'll get back to you."); return redirect(url_for("about"))

# ---------- admin ----------
@app.route("/admin/login", methods=["GET", "POST"])
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        r = db().execute("SELECT * FROM admins WHERE username=?", (request.form["username"],)).fetchone()
        if r and check_password_hash(r["password"], request.form["password"]):
            session["admin"] = r["username"]; return redirect(url_for("dashboard"))
        flash("Invalid username or password", "error")
    return render_template("admin/login.html")

@app.route("/admin/logout")
def logout(): session.clear(); return redirect(url_for("login"))

@app.route("/admin")
@login_required
def dashboard(): return render_template("admin/dashboard.html")

@app.route("/admin/api/stats")
@login_required
def stats():
    q = lambda s, a=(): db().execute(s, a).fetchone()[0]
    by_status = {s: q("SELECT COUNT(*) FROM orders WHERE status=?", (s,)) for s in STATUSES}
    recent = [dict(r) for r in db().execute("""SELECT o.id,o.customer,o.product,o.quantity,o.status,o.created,w.name worker
        FROM orders o LEFT JOIN workers w ON w.id=o.worker_id ORDER BY o.id DESC LIMIT 8""")]
    load = [dict(r) for r in db().execute("""SELECT w.name, COUNT(o.id) active FROM workers w
        LEFT JOIN orders o ON o.worker_id=w.id AND o.status IN ('Assigned','In Progress')
        WHERE w.active=1 GROUP BY w.id""")]
    return jsonify(total=q("SELECT COUNT(*) FROM orders"), today=q("SELECT COUNT(*) FROM orders WHERE date(created)=date('now')"),
        by_status=by_status, recent=recent, workers=q("SELECT COUNT(*) FROM workers WHERE active=1"),
        products=q("SELECT COUNT(*) FROM products WHERE published=1"), enquiries=q("SELECT COUNT(*) FROM enquiries"), load=load)

@app.route("/admin/orders")
@login_required
def orders():
    st = request.args.get("status")
    sql = "SELECT o.*, w.name worker FROM orders o LEFT JOIN workers w ON w.id=o.worker_id"
    rows = db().execute(sql + (" WHERE o.status=?" if st else "") + " ORDER BY o.id DESC", (st,) if st else ()).fetchall()
    ws = db().execute("SELECT * FROM workers WHERE active=1").fetchall()
    return render_template("admin/orders.html", orders=rows, workers=ws, statuses=STATUSES, current=st)

@app.route("/admin/orders/<int:oid>/update", methods=["POST"])
@login_required
def update_order(oid):
    wid = request.form.get("worker_id") or None
    status = request.form["status"]
    if wid and status == "New": status = "Assigned"
    disp = "CURRENT_TIMESTAMP" if status == "Dispatched" else "NULL"
    db().execute(f"UPDATE orders SET worker_id=?, status=?, dispatched={disp} WHERE id=?", (wid, status, oid))
    db().commit(); return redirect(request.referrer or url_for("orders"))

@app.route("/admin/orders/<int:oid>/delete", methods=["POST"])
@login_required
def delete_order(oid):
    db().execute("DELETE FROM orders WHERE id=?", (oid,)); db().commit(); return redirect(url_for("orders"))

@app.route("/admin/workers", methods=["GET", "POST"])
@login_required
def workers():
    if request.method == "POST":
        db().execute("INSERT INTO workers(name,phone) VALUES(?,?)", (request.form["name"], request.form["phone"]))
        db().commit(); return redirect(url_for("workers"))
    return render_template("admin/workers.html", workers=db().execute("SELECT * FROM workers").fetchall())

@app.route("/admin/workers/<int:wid>/toggle", methods=["POST"])
@login_required
def toggle_worker(wid):
    db().execute("UPDATE workers SET active=1-active WHERE id=?", (wid,)); db().commit(); return redirect(url_for("workers"))

@app.route("/admin/products")
@login_required
def admin_products():
    return render_template("admin/products.html", rows=db().execute("SELECT * FROM products ORDER BY id").fetchall())

@app.route("/admin/products/new", methods=["GET", "POST"])
@app.route("/admin/products/<int:pid>/edit", methods=["GET", "POST"])
@login_required
def product_form(pid=None):
    p = db().execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone() if pid else None
    if pid and not p: abort(404)
    if request.method == "POST":
        try:
            img = save_image() or (p["image"] if p else "")
            if not img: raise ValueError("Provide an image upload or URL")
            f = request.form; pub = 1 if f.get("published") == "on" else 0
            vals = (f["category"], f["name"], f["code"], f["summary"], img, pub)
            if p: db().execute("UPDATE products SET category=?,name=?,code=?,summary=?,image=?,published=? WHERE id=?", vals + (pid,))
            else: db().execute("INSERT INTO products(category,name,code,summary,image,published) VALUES(?,?,?,?,?,?)", vals)
            db().commit(); flash("Product saved"); return redirect(url_for("admin_products"))
        except ValueError as e: flash(str(e), "error")
    return render_template("admin/product_form.html", p=p)

@app.route("/admin/products/<int:pid>/delete", methods=["POST"])
@login_required
def product_delete(pid):
    db().execute("DELETE FROM products WHERE id=?", (pid,)); db().commit(); return redirect(url_for("admin_products"))

@app.route("/admin/enquiries")
@login_required
def enquiries():
    return render_template("admin/enquiries.html", rows=db().execute("SELECT * FROM enquiries ORDER BY id DESC").fetchall())

@app.route("/admin/password", methods=["GET", "POST"])
@login_required
def password():
    if request.method == "POST":
        r = db().execute("SELECT * FROM admins WHERE username=?", (session["admin"],)).fetchone()
        if check_password_hash(r["password"], request.form["old"]) and request.form["new"]:
            db().execute("UPDATE admins SET password=? WHERE id=?", (generate_password_hash(request.form["new"]), r["id"]))
            db().commit(); flash("Password changed")
        else: flash("Old password incorrect", "error")
    return render_template("admin/password.html")

init()
if __name__ == "__main__": app.run(debug=True)
