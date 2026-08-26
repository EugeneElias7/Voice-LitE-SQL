import sqlite3

# Check enterprise.db
conn = sqlite3.connect('backend/data/enterprise.db')
cursor = conn.cursor()
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = cursor.fetchall()
print('Tables in enterprise.db:', [t[0] for t in tables])

# Check if there's a hospital/medical database
import os
for f in os.listdir('backend/data'):
    if f.endswith('.db') or f.endswith('.sqlite'):
        path = f'backend/data/{f}'
        c = sqlite3.connect(path)
        cur = c.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = cur.fetchall()
        print(f'\nTables in {f}:', [t[0] for t in tables])
        c.close()