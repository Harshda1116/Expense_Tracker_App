import sqlite3

def add_budget_column():
    conn = sqlite3.connect("expense.db")
    try:
        conn.execute("ALTER TABLE users ADD COLUMN budget REAL DEFAULT 0")
        print("✅ Success: 'budget' column added to users table.")
    except sqlite3.OperationalError:
        print("ℹ️ Note: Column already exists.")
    conn.commit()
    conn.close()

if __name__ == "__main__":
    add_budget_column()