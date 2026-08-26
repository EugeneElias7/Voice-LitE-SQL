"""Voice-LitE-SQL -- Level 1: schema definition (single source of truth).

Everything about the enterprise database lives here: table definitions,
column types, primary/foreign keys, row counts, and the data pools used by
``backend.database.seed`` to generate realistic, reproducible seed data.
"""

import datetime

# Fixed seed -> deleting enterprise.db and regenerating produces an
# identical database every time.
SEED = 42

# ---------------------------------------------------------------------------
# Table definitions
# Ordered so that every FOREIGN KEY references an already-defined table.
# ---------------------------------------------------------------------------
TABLES = {
    "locations": {
        "columns": {
            "location_id": "INTEGER PRIMARY KEY",
            "city": "TEXT NOT NULL",
            "region": "TEXT NOT NULL",
        },
        "rows": 30,
    },
    "departments": {
        "columns": {
            "department_id": "INTEGER PRIMARY KEY",
            "department_name": "TEXT NOT NULL UNIQUE",
            "location_id": "INTEGER NOT NULL REFERENCES locations(location_id)",
            "budget": "REAL NOT NULL",
        },
        "rows": 15,
    },
    "employees": {
        "columns": {
            "employee_id": "INTEGER PRIMARY KEY",
            "employee_name": "TEXT NOT NULL",
            "department_id": "INTEGER NOT NULL REFERENCES departments(department_id)",
            "salary": "REAL NOT NULL",
            "hire_date": "TEXT NOT NULL",
        },
        "rows": 500,
    },
    "customers": {
        "columns": {
            "customer_id": "INTEGER PRIMARY KEY",
            "customer_name": "TEXT NOT NULL",
            "city": "TEXT NOT NULL",
        },
        "rows": 1000,
    },
    "products": {
        "columns": {
            "product_id": "INTEGER PRIMARY KEY",
            "product_name": "TEXT NOT NULL",
            "category": "TEXT NOT NULL",
            "price": "REAL NOT NULL",
        },
        "rows": 250,
    },
    "sales": {
        "columns": {
            "sale_id": "INTEGER PRIMARY KEY",
            "employee_id": "INTEGER NOT NULL REFERENCES employees(employee_id)",
            "customer_id": "INTEGER NOT NULL REFERENCES customers(customer_id)",
            "product_id": "INTEGER NOT NULL REFERENCES products(product_id)",
            "quantity": "INTEGER NOT NULL",
            "revenue": "REAL NOT NULL",
            "sale_date": "TEXT NOT NULL",
        },
        "rows": 5000,
    },
    "orders": {
        "columns": {
            "order_id": "INTEGER PRIMARY KEY",
            "customer_id": "INTEGER NOT NULL REFERENCES customers(customer_id)",
            "product_id": "INTEGER NOT NULL REFERENCES products(product_id)",
            "employee_id": "INTEGER NOT NULL REFERENCES employees(employee_id)",
            "quantity": "INTEGER NOT NULL",
            "order_total": "REAL NOT NULL",
            "order_date": "TEXT NOT NULL",
            "status": "TEXT NOT NULL",
        },
        "rows": 2500,
    },
}

# ---------------------------------------------------------------------------
# Data pools (realistic + deliberately NLP-friendly for later phonetic work)
# ---------------------------------------------------------------------------
DEPARTMENT_NAMES = [
    "Sales",
    "Marketing",
    "Finance",
    "Human Resources",
    "Engineering",
    "Operations",
    "Customer Support",
    "Information Technology",
    "Logistics",
    "Legal",
    "Product Management",
    "Research and Development",
    "Public Relations",
    "Purchasing",
    "Quality Assurance",
]

FIRST_NAMES = [
    "James", "Mary", "John", "Patricia", "Robert", "Jennifer", "Michael",
    "Linda", "David", "Elizabeth", "William", "Susan", "Richard", "Jessica",
    "Joseph", "Sarah", "Thomas", "Karen", "Charles", "Nancy", "Christopher",
    "Lisa", "Daniel", "Betty", "Matthew", "Margaret", "Anthony", "Sandra",
    "Mark", "Ashley", "Donald", "Kimberly", "Steven", "Emily", "Paul", "Donna",
]

LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
    "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez",
    "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin",
    "Lee", "Perez", "Thompson", "White", "Harris", "Sanchez", "Clark",
    "Ramirez", "Lewis", "Robinson", "Walker", "Young", "Allen", "King",
    "Wright", "Scott",
]

# 30 locations: (city, region)
CITY_REGIONS = [
    ("New York", "Northeast"), ("Boston", "Northeast"),
    ("Philadelphia", "Northeast"), ("Washington", "Northeast"),
    ("Atlanta", "Southeast"), ("Miami", "Southeast"),
    ("Charlotte", "Southeast"), ("Nashville", "Southeast"),
    ("Jacksonville", "Southeast"), ("Memphis", "Southeast"),
    ("Chicago", "Midwest"), ("Columbus", "Midwest"),
    ("Detroit", "Midwest"), ("Indianapolis", "Midwest"),
    ("Milwaukee", "Midwest"), ("Minneapolis", "Midwest"),
    ("Houston", "Southwest"), ("Dallas", "Southwest"),
    ("Phoenix", "Southwest"), ("San Antonio", "Southwest"),
    ("Austin", "Southwest"), ("Fort Worth", "Southwest"),
    ("Los Angeles", "West Coast"), ("San Diego", "West Coast"),
    ("San Jose", "West Coast"), ("San Francisco", "West Coast"),
    ("Seattle", "West Coast"), ("Portland", "West Coast"),
    ("Denver", "Mountain"), ("Las Vegas", "Mountain"),
]

# 10 categories x 5 base names x 5 suffixes = 250 products
PRODUCT_CATEGORIES = {
    "Electronics": ["Smartphone", "Laptop", "Tablet", "Headphones", "Smartwatch"],
    "Furniture": ["Desk Chair", "Office Desk", "Bookshelf", "Conference Table", "Filing Cabinet"],
    "Office Supplies": ["Printer Paper", "Ballpoint Pen", "Sticky Notes", "Notebook", "Desk Organizer"],
    "Apparel": ["Cotton T-Shirt", "Hoodie", "Polo Shirt", "Jacket", "Baseball Cap"],
    "Beverages": ["Roasted Coffee", "Green Tea", "Sparkling Water", "Orange Juice", "Energy Drink"],
    "Home Appliances": ["Coffee Maker", "Microwave", "Air Fryer", "Blender", "Toaster"],
    "Sports Equipment": ["Yoga Mat", "Dumbbell Set", "Jump Rope", "Resistance Band", "Treadmill"],
    "Books": ["Fiction Novel", "Science Book", "History Book", "Cooking Guide", "Business Book"],
    "Toys": ["Building Blocks", "Puzzle Set", "Remote Car", "Doll House", "Board Game"],
    "Automotive": ["Car Charger", "Phone Mount", "Floor Mats", "Jump Starter", "Air Freshener"],
}
PRODUCT_SUFFIXES = ["Plus", "Pro", "Max", "Mini", "Lite"]

ORDER_STATUSES = ["Pending", "Shipped", "Delivered", "Cancelled"]

DATE_RANGE = (datetime.date(1990, 1, 1), datetime.date(2025, 12, 31))
SALE_DATE_RANGE = (datetime.date(2022, 1, 1), datetime.date(2025, 12, 31))

SALARY_RANGE = (35_000, 150_000)
BUDGET_RANGE = (500_000, 5_000_000)
PRICE_RANGE = (5, 2_000)
QUANTITY_RANGE = (1, 20)
