from flask import Flask, render_template, request, redirect, url_for, session
from core.db import get_conn, init_db

app = Flask(__name__, template_folder="templates")
app.secret_key = "supersecret-change-me"  # ⚠️ replace for production

# --- DB INIT ---
init_db()


# --- ROUTES ---

@app.route("/")
def home():
    if "user" in session:
        return redirect(url_for("businesses"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        if username == "admin" and password == "admin":  # demo only
            session["user"] = username
            return redirect(url_for("businesses"))
        return "Invalid credentials", 401
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect(url_for("login"))


@app.route("/businesses", methods=["GET", "POST"])
def businesses():
    if "user" not in session:
        return redirect(url_for("login"))

    with get_conn() as con:
        if request.method == "POST":
            name = request.form.get("name")
            if name:
                slug = name.lower().replace(" ", "_")
                con.execute("INSERT INTO businesses (name, slug) VALUES (?, ?)", (name, slug))

        rows = con.execute("SELECT id, name FROM businesses ORDER BY name").fetchall()

    return render_template("businesses.html", businesses=rows)


@app.route("/business/<int:business_id>")
def business_dashboard(business_id):
    if "user" not in session:
        return redirect(url_for("login"))

    with get_conn() as con:
        business = con.execute("SELECT * FROM businesses WHERE id = ?", (business_id,)).fetchone()
        faqs = con.execute("SELECT * FROM faqs WHERE business_id = ?", (business_id,)).fetchall()
        info = con.execute("SELECT * FROM business_info WHERE business_id = ?", (business_id,)).fetchall()
        sessions = con.execute(
            "SELECT * FROM sessions WHERE business_id = ? ORDER BY started_at DESC",
            (business_id,)
        ).fetchall()
        appointments = con.execute(
            "SELECT * FROM appointments WHERE business_id = ? ORDER BY created_at DESC",
            (business_id,)
        ).fetchall()
        messages = con.execute(
            """SELECT * FROM messages
               WHERE session_id IN (SELECT id FROM sessions WHERE business_id = ?)
               ORDER BY id DESC LIMIT 50""",
            (business_id,)
        ).fetchall()

    business_data = {
        "name": business["name"],
        "faqs": {row["question"]: row["answer"] for row in faqs},
        "info": {row["key"]: row["value"] for row in info}
    }

    return render_template("dashboard.html",
                           business=business,
                           sessions=sessions,
                           messages=messages,
                           appointments=appointments,
                           business_data=business_data)


@app.route("/business/<int:business_id>/edit", methods=["GET", "POST"])
def edit_business(business_id):
    if "user" not in session:
        return redirect(url_for("login"))

    with get_conn() as con:
        business = con.execute("SELECT * FROM businesses WHERE id = ?", (business_id,)).fetchone()

        if request.method == "POST":
            action = request.form.get("action")

            if action == "update_name":
                new_name = request.form.get("name")
                con.execute("UPDATE businesses SET name = ? WHERE id = ?", (new_name, business_id))

            elif action == "add_faq":
                q = request.form.get("question")
                a = request.form.get("answer")
                if q and a:
                    con.execute("INSERT INTO faqs (business_id, question, answer) VALUES (?, ?, ?)",
                                (business_id, q, a))

            elif action == "edit_faq":
                faq_id = request.form.get("faq_id")
                new_q = request.form.get("question")
                new_a = request.form.get("answer")
                con.execute("UPDATE faqs SET question = ?, answer = ? WHERE id = ? AND business_id = ?",
                            (new_q, new_a, faq_id, business_id))

            elif action == "delete_faq":
                faq_id = request.form.get("faq_id")
                con.execute("DELETE FROM faqs WHERE id = ? AND business_id = ?", (faq_id, business_id))

            elif action == "update_info":
                key = request.form.get("key")
                value = request.form.get("value")
                existing = con.execute(
                    "SELECT id FROM business_info WHERE business_id = ? AND key = ?",
                    (business_id, key)
                ).fetchone()
                if existing:
                    con.execute("UPDATE business_info SET value = ? WHERE id = ?", (value, existing["id"]))
                else:
                    con.execute("INSERT INTO business_info (business_id, key, value) VALUES (?, ?, ?)",
                                (business_id, key, value))

            return redirect(url_for("edit_business", business_id=business_id))

        faqs = con.execute("SELECT * FROM faqs WHERE business_id = ?", (business_id,)).fetchall()
        info = con.execute("SELECT * FROM business_info WHERE business_id = ?", (business_id,)).fetchall()

    return render_template("edit_business.html", business=business, faqs=faqs, info=info)


@app.route("/business/<int:business_id>/delete", methods=["GET", "POST"])
def delete_business(business_id):
    if "user" not in session:
        return redirect(url_for("login"))

    with get_conn() as con:
        business = con.execute("SELECT * FROM businesses WHERE id = ?", (business_id,)).fetchone()

        if request.method == "POST":
            con.execute("DELETE FROM businesses WHERE id = ?", (business_id,))
            return redirect(url_for("businesses"))

    return render_template("delete_business.html", business=business)


# --- RUN ---
if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)

