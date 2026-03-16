from flask import Flask, render_template, request, redirect, flash, url_for, make_response
import sqlite3
import csv
import io
import os
from datetime import date, datetime
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = "secretkey"  # Change this to a random secret key for security

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

# ---------------- DATABASE ---------------- #

def get_db_connection():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    db_path = os.path.join(base_dir, "expense.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

def create_table():
    conn = get_db_connection()
    # USERS TABLE (Now includes budget)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE,
            password TEXT,
            budget REAL DEFAULT 0
        )
    """)
    # EXPENSES TABLE
    conn.execute("""
        CREATE TABLE IF NOT EXISTS expenses(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount REAL,
            category TEXT,
            date TEXT,
            note TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)
    # INCOME TABLE
    conn.execute("""
        CREATE TABLE IF NOT EXISTS income(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount REAL,
            date TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)
    conn.commit()
    conn.close()

# ---------------- USER CLASS ---------------- #

class User(UserMixin):
    def __init__(self, id, email):
        self.id = id
        self.email = email
        self.username = email.split('@')[0]

@login_manager.user_loader
def load_user(user_id):
    conn = get_db_connection()
    user = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    conn.close()
    if user:
        return User(user["id"], user["email"])
    return None

# ---------------- AUTH ROUTES ---------------- #

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form["email"]
        password = generate_password_hash(request.form["password"])

        conn = get_db_connection()
        try:
            conn.execute("INSERT INTO users (email, password) VALUES (?, ?)", (email, password))
            conn.commit()
        except sqlite3.IntegrityError:
            flash("Email already exists!", "danger")
            return redirect("/register")
        finally:
            conn.close()
        return redirect("/login")
    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]
        conn = get_db_connection()
        user = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        conn.close()
        if user and check_password_hash(user["password"], password):
            login_user(User(user["id"], user["email"]))
            return redirect("/dashboard")
        else:
            flash("Invalid email or password", "danger")
            return redirect("/login")
    return render_template("login.html")

@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect("/login")

# ---------------- DASHBOARD & FEATURES ---------------- #

@app.route("/")
def dashboard_front():
    if current_user.is_authenticated:
        return redirect("/dashboard")
    return render_template("index.html")

@app.route("/dashboard")
@login_required
def home():
    conn = get_db_connection()
    
    # 1. Date Filtering
    selected_month = request.args.get('month', datetime.now().strftime("%Y-%m"))

    # 2. Fetch Budget
    user_row = conn.execute("SELECT budget FROM users WHERE id=?", (current_user.id,)).fetchone()
    budget = user_row["budget"] if user_row and user_row["budget"] else 0

    # 3. Global Totals
    total_expenses = conn.execute("SELECT SUM(amount) FROM expenses WHERE user_id=?", (current_user.id,)).fetchone()[0] or 0
    income = conn.execute("SELECT SUM(amount) FROM income WHERE user_id=?", (current_user.id,)).fetchone()[0] or 0
    balance = income - total_expenses

    # 4. Filtered Data (By Month)
    expenses = conn.execute(
        "SELECT * FROM expenses WHERE user_id=? AND date LIKE ? ORDER BY date DESC", 
        (current_user.id, selected_month + "%")
    ).fetchall()

    monthly_expense = conn.execute(
        "SELECT SUM(amount) FROM expenses WHERE user_id=? AND date LIKE ?", 
        (current_user.id, selected_month + "%")
    ).fetchone()[0] or 0

    monthly_income = conn.execute(
        "SELECT SUM(amount) FROM income WHERE user_id=? AND date LIKE ?", 
        (current_user.id, selected_month + "%")
    ).fetchone()[0] or 0

    monthly_balance = monthly_income - monthly_expense

    # 5. Budget Logic
    budget_percentage = 0
    if budget > 0:
        budget_percentage = int((monthly_expense / budget) * 100)
    
    bar_color = "bg-success"
    if budget_percentage > 50: bar_color = "bg-warning"
    if budget_percentage > 90: bar_color = "bg-danger"

    # 6. Charts
    category_data = conn.execute(
        "SELECT category, SUM(amount) as total FROM expenses WHERE user_id=? AND date LIKE ? GROUP BY category",
        (current_user.id, selected_month + "%")
    ).fetchall()
    labels = [row["category"] for row in category_data]
    values = [row["total"] for row in category_data]

    conn.close()
    today = date.today().isoformat()

    return render_template(
        "dashboard.html",
        expenses=expenses, total=total_expenses, income=income, balance=balance,
        today=today, monthly_expense=monthly_expense, monthly_income=monthly_income,
        monthly_balance=monthly_balance, budget=budget, budget_percentage=budget_percentage,
        bar_color=bar_color, labels=labels, values=values, selected_month=selected_month
    )

@app.route("/set_budget", methods=["POST"])
@login_required
def set_budget():
    new_budget = request.form["budget"]
    conn = get_db_connection()
    conn.execute("UPDATE users SET budget=? WHERE id=?", (new_budget, current_user.id))
    conn.commit()
    conn.close()
    return redirect("/dashboard")

@app.route('/export')
@login_required
def export():
    conn = get_db_connection()
    expenses = conn.execute("SELECT * FROM expenses WHERE user_id=?", (current_user.id,)).fetchall()
    conn.close()

    si = io.StringIO()
    cw = csv.writer(si)
    cw.writerow(['Amount', 'Category', 'Date', 'Note'])
    for row in expenses:
        cw.writerow([row['amount'], row['category'], row['date'], row['note']])
    
    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = "attachment; filename=my_expenses.csv"
    output.headers["Content-type"] = "text/csv"
    return output

# ---------------- CRUD ROUTES ---------------- #

@app.route("/add", methods=["POST"])
@login_required
def add_expenses():
    amount = request.form["amount"]
    category = request.form["category"]
    date_val = request.form["date"]
    note = request.form["note"]
    conn = get_db_connection()
    conn.execute("INSERT INTO expenses (user_id, amount, category, date, note) VALUES (?, ?, ?, ?, ?)",
                 (current_user.id, amount, category, date_val, note))
    conn.commit()
    conn.close()
    return redirect("/dashboard")

@app.route("/income", methods=["POST"])
@login_required
def update_income():
    amount = request.form["income"]
    date_val = request.form["income_date"]
    conn = get_db_connection()
    conn.execute("INSERT INTO income (user_id, amount, date) VALUES (?, ?, ?)",
                 (current_user.id, amount, date_val))
    conn.commit()
    conn.close()
    return redirect("/dashboard")

@app.route("/edit/<int:id>", methods=["GET", "POST"])
@login_required
def edit_expenses(id):
    conn = get_db_connection()
    if request.method == "POST":
        amount = request.form["amount"]
        category = request.form["category"]
        date_val = request.form["date"]
        note = request.form["note"]
        conn.execute("UPDATE expenses SET amount=?, category=?, date=?, note=? WHERE id=? AND user_id=?",
                     (amount, category, date_val, note, id, current_user.id))
        conn.commit()
        conn.close()
        return redirect("/dashboard")
    
    expense = conn.execute("SELECT * FROM expenses WHERE id=? AND user_id=?", (id, current_user.id)).fetchone()
    conn.close()
    return render_template("edit.html", expense=expense)

@app.route("/delete/<int:id>")
@login_required
def delete_expense(id):
    conn = get_db_connection()
    conn.execute("DELETE FROM expenses WHERE id=? AND user_id=?", (id, current_user.id))
    conn.commit()
    conn.close()
    return redirect("/dashboard")

if __name__ == "__main__":
    create_table()
    app.run(debug=True)