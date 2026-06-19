"""Generates sample_data/orders.csv, products.csv, payments.csv with
deliberately injected errors (bad phone lengths, bad dates, missing
fields, duplicate ids, orphan foreign keys) so the validator has
something real to demonstrate on."""
import random
import csv
from datetime import datetime, timedelta

random.seed(42)

COUNTRIES = [("IN", "+91", 10), ("SG", "+65", 8), ("US", "+1", 10), ("GB", "+44", 10), ("AE", "+971", 9)]
NAMES = ["Aarav Mehta", "Wei Lin", "John Carter", "Olivia Brown", "Fatima Noor", "Karan Shah",
         "Mei Tan", "James Wright", "Sara Khan", "Rohan Gupta"]
PRODUCTS = [("P001", "Wireless Mouse", "Electronics", 799), ("P002", "Yoga Mat", "Fitness", 1299),
            ("P003", "Coffee Mug", "Home", 349), ("P004", "Bluetooth Speaker", "Electronics", 2499),
            ("P005", "Running Shoes", "Footwear", 3499)]
PAYMENT_MODES = ["UPI", "Credit Card", "cod", " Debit Card ", "NetBanking", "upi"]

orders_rows = []
products_rows = []
payments_rows = []

base_date = datetime(2026, 5, 1)

for i in range(1, 121):
    order_id = f"ORD{1000 + i}"
    country, dial, length = random.choice(COUNTRIES)
    name = random.choice(NAMES)

    # Inject phone errors ~15% of the time
    if random.random() < 0.15:
        phone = "".join([str(random.randint(0, 9)) for _ in range(length - random.choice([1, 2, 3]))])
    else:
        phone = "".join([str(random.randint(0, 9)) for _ in range(length)])
    if random.random() < 0.5:
        phone = dial.replace("+", "") + phone  # sometimes dial code is embedded

    order_date = base_date + timedelta(days=random.randint(0, 45), hours=random.randint(0, 23))
    # Inject date-format errors ~10% of the time
    if random.random() < 0.1:
        date_str = order_date.strftime("%d/%m/%Y")  # wrong format vs the rest
    else:
        date_str = order_date.strftime("%Y-%m-%d")

    amount = round(random.uniform(200, 8000), 2)
    if random.random() < 0.05:
        amount = -abs(amount)  # injected bad value

    # Inject a missing customer name ~5% of the time
    if random.random() < 0.05:
        name = ""

    orders_rows.append([order_id, f"CUST{500+i}", name, phone, country, date_str,
                         "Delivered" if random.random() > 0.2 else "Pending", amount])

    # 1-3 product lines per order
    for _ in range(random.randint(1, 3)):
        pid, pname, cat, price = random.choice(PRODUCTS)
        qty = random.randint(1, 5)
        if random.random() < 0.04:
            qty = 0  # injected bad value
        products_rows.append([order_id, pid, pname, cat, qty, price])

    # Payment row; occasionally reference a non-existent order (orphan FK)
    pay_order_id = order_id if random.random() > 0.04 else f"ORD{9999}"
    mode = random.choice(PAYMENT_MODES)
    pay_date = order_date + timedelta(hours=random.randint(0, 5))
    payments_rows.append([f"PAY{2000+i}", pay_order_id, mode, pay_date.strftime("%Y-%m-%d %H:%M:%S"), amount])

# Add 2 duplicate order_ids on purpose
orders_rows.append(orders_rows[3][:])
orders_rows.append(orders_rows[10][:])

with open("/home/claude/xeno-transaction-validator/sample_data/orders.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["order_id", "customer_id", "customer_name", "phone_number", "country_code",
                "order_date", "order_status", "total_amount"])
    w.writerows(orders_rows)

with open("/home/claude/xeno-transaction-validator/sample_data/products.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["order_id", "product_id", "product_name", "category", "quantity", "unit_price"])
    w.writerows(products_rows)

with open("/home/claude/xeno-transaction-validator/sample_data/payments.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["payment_id", "order_id", "payment_mode", "payment_datetime", "amount"])
    w.writerows(payments_rows)

print(f"orders={len(orders_rows)} products={len(products_rows)} payments={len(payments_rows)}")
