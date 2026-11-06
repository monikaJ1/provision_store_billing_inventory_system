# Provision Store Billing & Inventory System

Flask project with five modules: User Management (Admin/Staff), Product & Stock Management, Customer Management, Billing (Normal/GST), and Sales/Inventory Reports. Includes PDF invoices and barcode input/scanning.

## Run on Windows
1. Extract this ZIP and open the extracted folder in VS Code.
2. Terminal > New Terminal:
   `py -m venv .venv`
   ` .\.venv\Scripts\Activate.ps1`
3. Install: `pip install -r requirements.txt`
4. Start: `python app.py`
5. Open http://127.0.0.1:5000/setup and create the first Admin account.
6. Sign in and create employee accounts under Staff Accounts.

## Barcode
Add a barcode number to each product first. On Billing, scan using the device camera or type the barcode into the search field. Camera scanning uses a browser library from a CDN and requires internet plus camera permission; camera access requires HTTPS or localhost.

## GST note
GST is calculated using each product's configured GST percentage. Verify applicable GST rates, HSN codes and statutory invoice requirements with an accountant before real business use. This is an academic/demo starter, not certified accounting software.

## Free cloud deployment (example)
Push source files to GitHub (never upload `.env` or database files). Deploy a Render Web Service with build command `pip install -r requirements.txt` and start command `gunicorn app:app`. Create a PostgreSQL database with a provider such as Neon and set `DATABASE_URL` and a strong `SECRET_KEY` in the hosting dashboard. Free plans, sleep behavior, storage and database retention change; check current terms before use. Render free web services may sleep when idle. Back up business data regularly.
