
import sqlite3
import os
import uuid
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, jsonify, g, abort
)
from werkzeug.security import generate_password_hash, check_password_hash


BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "galexy.db")
UPLOADS = os.path.join(BASE, "static", "uploads")

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-change-me")
app.config["MAX_CONTENT_LENGTH"] = 15 * 1024 * 1024

CATEGORIES = [
    "Smart Rack",
    "CAC / HAC",
    "Cage",
    "ODU",
    "Customize Solutions"
]

SEED = [
    (
        "Smart Rack", "Smart Rack", "GS-PR-100",
        "Modular racks that keep parts and components organised, easy to find and quick to access on the shop floor.",
        "/static/products/part-rack.jpg"
    ),
    (
        "CAC / HAC", "CAC Rack", "GS-CA-200",
        "Cold Aisle Containment seals the cold aisle so cool air reaches your equipment, improving cooling efficiency and cutting energy use.",
        "/static/products/cac.jpg"
    ),
    (
        "CAC / HAC", "HAC Rack", "GS-HA-210",
        "Hot Aisle Containment captures hot exhaust air and sends it back to cooling, keeping the room temperature stable.",
        "/static/products/hac.jpg"
    ),
    (
        "Cage", "Mesh Cage", "GS-CG-300",
        "Welded-mesh cage with open airflow and full visibility. Secure storage for equipment, parts and stock.",
        "/static/products/mesh-cage.jpg"
    ),
    (
        "Cage", "Opac Cage", "GS-CG-310",
        "Opaque-panel cage that hides what is inside. Adds privacy and protection with a lockable door.",
        "/static/products/opac-cage.jpg"
    ),
    (
        "ODU", "ODU", "GS-OD-400",
        "Outdoor enclosure built for rain, dust and sun. Protects electrical and network equipment in harsh conditions.",
        "/static/products/odo.jpg"
    ),
    (
        "Customize Solutions", "Customize Solutions", "GS-CU-500",
        "Need a different size, finish or layout? Tell us your requirement and we build it to order.",
        "/static/products/custom.jpg"
    ),
]

STATUSES = ["New", "Assigned", "In Progress", "Ready", "Dispatched"]


def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close(e=None):
    connection = g.pop("db", None)
    if connection:
        connection.close()


def init():
    os.makedirs(UPLOADS, exist_ok=True)

    c = sqlite3.connect(DB)

    c.executescript("""
    CREATE TABLE IF NOT EXISTS admins (
        id INTEGER PRIMARY KEY,
        username TEXT UNIQUE,
        password TEXT
    );

    CREATE TABLE IF NOT EXISTS workers (
        id INTEGER PRIMARY KEY,
        name TEXT,
        phone TEXT,
        active INTEGER DEFAULT 1
    );

    CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY,
        category TEXT,
        name TEXT,
        code TEXT,
        summary TEXT,
        image TEXT,
        published INTEGER DEFAULT 1
    );

    CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY,
        customer TEXT,
        phone TEXT,
        email TEXT,
        product TEXT,
        quantity INTEGER,
        details TEXT,
        status TEXT DEFAULT 'New',
        worker_id INTEGER,
        created TEXT DEFAULT CURRENT_TIMESTAMP,
        dispatched TEXT
    );

    CREATE TABLE IF NOT EXISTS enquiries (
        id INTEGER PRIMARY KEY,
        name TEXT,
        phone TEXT,
        message TEXT,
        created TEXT DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # Create the first admin only when no admin exists.
    # Credentials must be provided through environment variables.
    if not c.execute("SELECT 1 FROM admins").fetchone():
        username = os.environ.get("ADMIN_USERNAME")
        password = os.environ.get("ADMIN_PASSWORD")

        if username and password:
            c.execute(
                "INSERT INTO admins(username, password) VALUES(?, ?)",
                (username, generate_password_hash(password))
            )

    # Add sample products only when the products table is empty.
    if not c.execute("SELECT 1 FROM products").fetchone():
        c.executemany(
            """INSERT INTO products
               (category, name, code, summary, image)
               VALUES (?, ?, ?, ?, ?)""",
            SEED
        )

    # Update old product image paths if an older database is used.
    c.execute("""
        UPDATE products
        SET image = replace(
            replace(image, '/static/img/', '/static/products/'),
            '.svg', '.jpg'
        )
        WHERE image LIKE '/static/img/%.svg'
    """)

    for old, new in (
        ("CAC - Cold Aisle Containment", "CAC Rack"),
        ("HAC - Hot Aisle Containment", "HAC Rack")
    ):
        c.execute(
            "UPDATE products SET name=? WHERE name=?",
            (new, old)
        )

    # Update older sample descriptions without overwriting custom descriptions.
    old_summaries = [
        "Modular rack for organising parts and components.",
        "Contain cold air to improve cooling efficiency.",
        "Capture and channel hot exhaust air.",
        "Ventilated welded-mesh cage for secure storage.",
        "Opaque-panel cage for privacy and protection.",
        "Outdoor enclosure for harsh weather conditions.",
        "Tell us your size and use. We build it to order."
    ]

    for category, name, code, summary, image in SEED:
        placeholders = ",".join("?" for _ in old_summaries)
        c.execute(
            f"""UPDATE products SET summary=?
                WHERE name=? AND summary IN ({placeholders})""",
            (summary, name, *old_summaries)
        )

    c.commit()
    c.close()


def login_required(f):
    @wraps(f)
    def w(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return w


def save_image():
    uploaded = request.files.get("image_file")

    if uploaded and uploaded.filename:
        head = uploaded.read(16)
        uploaded.seek(0)

        if head.startswith(b"\xff\xd8\xff"):
            ext = ".jpg"
        elif head.startswith(b"\x89PNG"):
            ext = ".png"
        elif head[:4] == b"RIFF" and head[8:12] == b"WEBP":
            ext = ".webp"
        elif head[:6] in (b"GIF87a", b"GIF89a"):
            ext = ".gif"
        else:
            raise ValueError(
                "Please upload a valid JPG, PNG, WEBP or GIF image. "
                "Convert HEIC photos to JPG first."
            )

        filename = uuid.uuid4().hex + ext
        uploaded.save(os.path.join(UPLOADS, filename))
        return "/static/uploads/" + filename

    return request.form.get("image_url", "").strip()


@app.errorhandler(413)
def too_big(e):
    flash(
        "That image is too large (maximum 15 MB). "
        "Please make it smaller and try again.",
        "error"
    )
    return redirect(request.referrer or url_for("dashboard"))


# ---------------- PUBLIC WEBSITE ----------------

@app.context_processor
def inject():
    return {"categories": CATEGORIES}


@app.route("/")
def home():
    rows = db().execute(
        "SELECT * FROM products WHERE published=1 ORDER BY id"
    ).fetchall()

    sliders = [
        (row["name"], row["summary"], row["image"])
        for row in rows
    ]

    return render_template("home.html", sliders=sliders)


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/products")
def products():
    rows = db().execute(
        "SELECT * FROM products WHERE published=1 ORDER BY id"
    ).fetchall()

    category = request.args.get("category")

    groups = {
        cat: [row for row in rows if row["category"] == cat]
        for cat in CATEGORIES
        if not category or cat == category
    }

    return render_template(
        "products.html",
        groups=groups,
        current=category
    )


@app.route("/order", methods=["GET", "POST"])
def order():
    product_rows = db().execute(
        """SELECT name, code, summary, image
           FROM products
           WHERE published=1
           ORDER BY id"""
    ).fetchall()

    product_list = [dict(row) for row in product_rows]
    product_names = [p["name"] for p in product_list]

    if request.method == "POST":
        form = request.form

        customer = form.get("customer", "").strip()
        phone = form.get("phone", "").strip()
        email = form.get("email", "").strip()
        product = form.get("product", "").strip()
        details = form.get("details", "").strip()

        try:
            quantity = int(form.get("quantity", "1"))
        except (ValueError, TypeError):
            quantity = 0

        if (
            not customer or not phone or
            product not in product_names or quantity < 1
        ):
            flash("Please enter valid order details.", "error")
            return redirect(url_for("order"))

        db().execute(
            """INSERT INTO orders
               (customer, phone, email, product, quantity, details)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (customer, phone, email, product, quantity, details)
        )
        db().commit()

        flash("Order received. We will contact you soon.")
        return redirect(url_for("order", product=product))

    selected = request.args.get("product", "")

    if selected not in product_names and product_names:
        selected = product_names[0]

    return render_template(
        "order.html",
        products=product_list,
        selected=selected
    )


@app.route("/contact", methods=["POST"])
def contact():
    name = request.form.get("name", "").strip()
    phone = request.form.get("phone", "").strip()
    message = request.form.get("message", "").strip()

    if not name or not phone or not message:
        flash("Please complete all contact fields.", "error")
        return redirect(url_for("about"))

    db().execute(
        "INSERT INTO enquiries(name, phone, message) VALUES(?, ?, ?)",
        (name, phone, message)
    )
    db().commit()

    flash("Thanks, we'll get back to you.")
    return redirect(url_for("about"))


# ---------------- ADMIN LOGIN ----------------

@app.route("/admin/login", methods=["GET", "POST"])
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        row = db().execute(
            "SELECT * FROM admins WHERE username=?",
            (username,)
        ).fetchone()

        if row and check_password_hash(row["password"], password):
            session.clear()
            session["admin"] = row["username"]
            return redirect(url_for("dashboard"))

        flash("Invalid username or password", "error")

    return render_template("admin/login.html")


@app.route("/admin/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/admin")
@login_required
def dashboard():
    return render_template("admin/dashboard.html")


@app.route("/admin/api/stats")
@login_required
def stats():
    def count(sql, params=()):
        return db().execute(sql, params).fetchone()[0]

    by_status = {
        status: count(
            "SELECT COUNT(*) FROM orders WHERE status=?",
            (status,)
        )
        for status in STATUSES
    }

    recent = [
        dict(row)
        for row in db().execute("""
            SELECT o.id, o.customer, o.product, o.quantity,
                   o.status, o.created, w.name AS worker
            FROM orders o
            LEFT JOIN workers w ON w.id=o.worker_id
            ORDER BY o.id DESC
            LIMIT 8
        """)
    ]

    load = [
        dict(row)
        for row in db().execute("""
            SELECT w.name, COUNT(o.id) AS active
            FROM workers w
            LEFT JOIN orders o
              ON o.worker_id=w.id
             AND o.status IN ('Assigned', 'In Progress')
            WHERE w.active=1
            GROUP BY w.id
        """)
    ]

    return jsonify(
        total=count("SELECT COUNT(*) FROM orders"),
        today=count(
            "SELECT COUNT(*) FROM orders WHERE date(created)=date('now')"
        ),
        by_status=by_status,
        recent=recent,
        workers=count("SELECT COUNT(*) FROM workers WHERE active=1"),
        products=count("SELECT COUNT(*) FROM products WHERE published=1"),
        enquiries=count("SELECT COUNT(*) FROM enquiries"),
        load=load
    )


# ---------------- ORDER MANAGEMENT ----------------

@app.route("/admin/orders")
@login_required
def orders():
    status = request.args.get("status")

    sql = """
        SELECT o.*, w.name AS worker
        FROM orders o
        LEFT JOIN workers w ON w.id=o.worker_id
    """

    if status in STATUSES:
        sql += " WHERE o.status=?"
        rows = db().execute(
            sql + " ORDER BY o.id DESC",
            (status,)
        ).fetchall()
    else:
        status = None
        rows = db().execute(sql + " ORDER BY o.id DESC").fetchall()

    workers_list = db().execute(
        "SELECT * FROM workers WHERE active=1"
    ).fetchall()

    return render_template(
        "admin/orders.html",
        orders=rows,
        workers=workers_list,
        statuses=STATUSES,
        current=status
    )


@app.route("/admin/orders/<int:oid>/update", methods=["POST"])
@login_required
def update_order(oid):
    worker_id = request.form.get("worker_id") or None
    status = request.form.get("status", "")

    if status not in STATUSES:
        abort(400)

    if worker_id:
        worker = db().execute(
            "SELECT id FROM workers WHERE id=? AND active=1",
            (worker_id,)
        ).fetchone()

        if not worker:
            abort(400)

    if worker_id and status == "New":
        status = "Assigned"

    dispatched = (
        "CURRENT_TIMESTAMP" if status == "Dispatched" else "NULL"
    )

    db().execute(
        f"""UPDATE orders
            SET worker_id=?, status=?, dispatched={dispatched}
            WHERE id=?""",
        (worker_id, status, oid)
    )
    db().commit()

    return redirect(request.referrer or url_for("orders"))


@app.route("/admin/orders/<int:oid>/delete", methods=["POST"])
@login_required
def delete_order(oid):
    db().execute("DELETE FROM orders WHERE id=?", (oid,))
    db().commit()
    return redirect(url_for("orders"))


# ---------------- WORKERS ----------------

@app.route("/admin/workers", methods=["GET", "POST"])
@login_required
def workers():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()

        if not name or not phone:
            flash("Enter the worker's name and phone number.", "error")
        else:
            db().execute(
                "INSERT INTO workers(name, phone) VALUES(?, ?)",
                (name, phone)
            )
            db().commit()

        return redirect(url_for("workers"))

    worker_rows = db().execute(
        "SELECT * FROM workers ORDER BY id DESC"
    ).fetchall()

    return render_template(
        "admin/workers.html",
        workers=worker_rows
    )


@app.route("/admin/workers/<int:wid>/toggle", methods=["POST"])
@login_required
def toggle_worker(wid):
    db().execute(
        "UPDATE workers SET active=1-active WHERE id=?",
        (wid,)
    )
    db().commit()
    return redirect(url_for("workers"))


# ---------------- PRODUCT MANAGEMENT ----------------

@app.route("/admin/products")
@login_required
def admin_products():
    rows = db().execute(
        "SELECT * FROM products ORDER BY id"
    ).fetchall()

    return render_template("admin/products.html", rows=rows)


@app.route("/admin/products/new", methods=["GET", "POST"])
@app.route("/admin/products/<int:pid>/edit", methods=["GET", "POST"])
@login_required
def product_form(pid=None):
    product = None

    if pid is not None:
        product = db().execute(
            "SELECT * FROM products WHERE id=?",
            (pid,)
        ).fetchone()

        if not product:
            abort(404)

    if request.method == "POST":
        try:
            image = save_image() or (
                product["image"] if product else ""
            )

            if not image:
                raise ValueError("Provide an image upload or URL.")

            form = request.form
            category = form.get("category", "").strip()
            name = form.get("name", "").strip()
            code = form.get("code", "").strip()
            summary = form.get("summary", "").strip()
            published = 1 if form.get("published") == "on" else 0

            if (
                category not in CATEGORIES or
                not name or not code or not summary
            ):
                raise ValueError("Please complete all product fields.")

            values = (
                category, name, code, summary, image, published
            )

            if product:
                db().execute(
                    """UPDATE products
                       SET category=?, name=?, code=?, summary=?,
                           image=?, published=?
                       WHERE id=?""",
                    values + (pid,)
                )
            else:
                db().execute(
                    """INSERT INTO products
                       (category, name, code, summary, image, published)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    values
                )

            db().commit()
            flash("Product saved successfully.")
            return redirect(url_for("admin_products"))

        except ValueError as error:
            flash(str(error), "error")

    return render_template(
        "admin/product_form.html",
        p=product
    )


@app.route("/admin/products/<int:pid>/delete", methods=["POST"])
@login_required
def product_delete(pid):
    db().execute("DELETE FROM products WHERE id=?", (pid,))
    db().commit()
    return redirect(url_for("admin_products"))


# ---------------- CUSTOMER ENQUIRIES ----------------

@app.route("/admin/enquiries")
@login_required
def enquiries():
    rows = db().execute(
        "SELECT * FROM enquiries ORDER BY id DESC"
    ).fetchall()

    return render_template("admin/enquiries.html", rows=rows)


# ---------------- CHANGE ADMIN PASSWORD ----------------

@app.route("/admin/password", methods=["GET", "POST"])
@login_required
def password():
    if request.method == "POST":
        row = db().execute(
            "SELECT * FROM admins WHERE username=?",
            (session["admin"],)
        ).fetchone()

        if not row:
            session.clear()
            return redirect(url_for("login"))

        old_password = request.form.get("old", "")
        new_password = request.form.get("new", "")

        if not check_password_hash(row["password"], old_password):
            flash("Old password incorrect.", "error")

        elif len(new_password) < 8:
            flash(
                "New password must be at least 8 characters.",
                "error"
            )

        elif new_password == old_password:
            flash(
                "Choose a different password from your old password.",
                "error"
            )

        else:
            db().execute(
                "UPDATE admins SET password=? WHERE id=?",
                (
                    generate_password_hash(new_password),
                    row["id"]
                )
            )
            db().commit()
            flash("Password changed successfully.")

    return render_template("admin/password.html")


# Create database tables and seed sample products at startup.
init()


if __name__ == "__main__":
    app.run(debug=True)
