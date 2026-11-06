import base64
import requests
from dotenv import load_dotenv
load_dotenv()
import os
from datetime import datetime, date
from decimal import Decimal
from io import BytesIO
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, abort, send_file, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import func, or_
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm

app=Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY", "change-this-before-deployment")
url=os.getenv("DATABASE_URL","sqlite:///store.db")
if url.startswith("postgres://"): url=url.replace("postgres://","postgresql://",1)
app.config["SQLALCHEMY_DATABASE_URI"]=url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"]=False
db=SQLAlchemy(app)
lm=LoginManager(app); lm.login_view="login"

class User(UserMixin,db.Model):
    id=db.Column(db.Integer,primary_key=True); username=db.Column(db.String(80),unique=True,nullable=False)
    password=db.Column(db.String(255),nullable=False); role=db.Column(db.String(12),default="staff"); active=db.Column(db.Boolean,default=True)
    def set_password(self,p): self.password=generate_password_hash(p)
    def verify(self,p): return check_password_hash(self.password,p)
class Product(db.Model):
    id=db.Column(db.Integer,primary_key=True); name=db.Column(db.String(140),nullable=False)
    barcode=db.Column(db.String(80),unique=True); category=db.Column(db.String(80),default="General")
    price=db.Column(db.Numeric(12,2),nullable=False); stock=db.Column(db.Integer,default=0)
    gst=db.Column(db.Numeric(5,2),default=0); low_stock=db.Column(db.Integer,default=5); active=db.Column(db.Boolean,default=True)
class Customer(db.Model):
    id=db.Column(db.Integer,primary_key=True); name=db.Column(db.String(120),nullable=False)
    phone=db.Column(db.String(20)); email=db.Column(db.String(160))
class Invoice(db.Model):
    id=db.Column(db.Integer,primary_key=True); number=db.Column(db.String(50),unique=True)
    created=db.Column(db.DateTime,default=datetime.utcnow); customer_id=db.Column(db.Integer,db.ForeignKey("customer.id"))
    user_id=db.Column(db.Integer,db.ForeignKey("user.id")); kind=db.Column(db.String(10))
    subtotal=db.Column(db.Numeric(12,2)); discount=db.Column(db.Numeric(12,2)); tax=db.Column(db.Numeric(12,2)); total=db.Column(db.Numeric(12,2))
    customer=db.relationship("Customer"); cashier=db.relationship("User")
    items=db.relationship("Item",cascade="all,delete-orphan",backref="invoice")
class Item(db.Model):
    id=db.Column(db.Integer,primary_key=True); invoice_id=db.Column(db.Integer,db.ForeignKey("invoice.id"))
    product_id=db.Column(db.Integer,db.ForeignKey("product.id")); name=db.Column(db.String(140))
    qty=db.Column(db.Integer); price=db.Column(db.Numeric(12,2)); gst=db.Column(db.Numeric(5,2)); amount=db.Column(db.Numeric(12,2))
@lm.user_loader
def load(uid): return db.session.get(User,int(uid))
def admin(fn):
    @wraps(fn)
    @login_required
    def inner(*a,**k):
        if current_user.role!="admin": abort(403)
        return fn(*a,**k)
    return inner
@app.context_processor
def globals():
    return {"low_count":Product.query.filter(Product.active.is_(True),Product.stock<=Product.low_stock).count() if current_user.is_authenticated else 0}
@app.route("/setup",methods=["GET","POST"])
def setup():
    if User.query.first(): return redirect(url_for("login"))
    if request.method=="POST":
        u=request.form["username"].strip(); p=request.form["password"]
        if len(u)<3 or len(p)<8: flash("Username must be 3+ characters and password 8+ characters.","danger")
        else:
            x=User(username=u,role="admin"); x.set_password(p); db.session.add(x); db.session.commit()
            flash("Admin account created. Please sign in.","success"); return redirect(url_for("login"))
    return render_template("setup.html")
@app.route("/login",methods=["GET","POST"])
def login():
    if request.method=="POST":
        u=User.query.filter_by(username=request.form["username"].strip(),active=True).first()
        if u and u.verify(request.form["password"]): login_user(u); return redirect(url_for("dashboard"))
        flash("Incorrect username or password.","danger")
    return render_template("login.html")
@app.route("/logout")
@login_required
def logout(): logout_user(); return redirect(url_for("login"))
@app.route("/")
@login_required
def dashboard():
    today=date.today()
    today_sum=db.session.query(func.coalesce(func.sum(Invoice.total),0)).filter(func.date(Invoice.created)==today.isoformat()).scalar()
    month_start=datetime(today.year,today.month,1); month_end=datetime(today.year+1,1,1) if today.month==12 else datetime(today.year,today.month+1,1)
    month_sum=db.session.query(func.coalesce(func.sum(Invoice.total),0)).filter(Invoice.created>=month_start,Invoice.created<month_end).scalar()
    return render_template("dashboard.html",today_sum=today_sum,month_sum=month_sum,product_count=Product.query.filter_by(active=True).count(),invoice_count=Invoice.query.count(),recent=Invoice.query.order_by(Invoice.created.desc()).limit(8).all())
@app.route("/products",methods=["GET","POST"])
@login_required
def products():
    if request.method=="POST":
        try:
            p=Product(name=request.form["name"].strip(),barcode=request.form.get("barcode","").strip() or None,category=request.form.get("category","General"),price=Decimal(request.form["price"]),stock=int(request.form["stock"]),gst=Decimal(request.form.get("gst","0")),low_stock=int(request.form.get("low_stock","5")))
            if not p.name or p.price<0 or p.stock<0 or p.gst<0 or p.gst>100: raise ValueError("Check product details.")
            db.session.add(p); db.session.commit(); flash("Product added.","success")
        except Exception as e: db.session.rollback(); flash("Could not add product: "+str(e),"danger")
        return redirect(url_for("products"))
    q=request.args.get("q",""); query=Product.query.filter_by(active=True)
    if q: query=query.filter(or_(Product.name.ilike(f"%{q}%"),Product.barcode.ilike(f"%{q}%"),Product.category.ilike(f"%{q}%")))
    return render_template("products.html",products=query.order_by(Product.name).all(),q=q)
@app.route("/products/<int:pid>/archive",methods=["POST"])
@admin
def archive(pid):
    p=Product.query.get_or_404(pid); p.active=False; db.session.commit(); flash("Product archived.","success"); return redirect(url_for("products"))
@app.route("/customers",methods=["GET","POST"])
@login_required
def customers():
    if request.method=="POST":
        c=Customer(name=request.form["name"].strip(),phone=request.form.get("phone",""),email=request.form.get("email",""))
        if not c.name: flash("Name is required.","danger")
        else: db.session.add(c); db.session.commit(); flash("Customer saved.","success")
        return redirect(url_for("customers"))
    q=request.args.get("q",""); query=Customer.query
    if q: query=query.filter(or_(Customer.name.ilike(f"%{q}%"),Customer.phone.ilike(f"%{q}%")))
    return render_template("customers.html",customers=query.order_by(Customer.name).all(),q=q)
@app.route("/billing/add-customer", methods=["POST"])
@login_required
def add_billing_customer():
    try:
        data = request.get_json(silent=True) or {}

        name = (data.get("name") or "").strip()
        phone = (data.get("phone") or "").strip()
        email = (data.get("email") or "").strip()

        if not name:
            return jsonify({"error": "Customer name is required."}), 400

        customer = Customer(
            name=name,
            phone=phone,
            email=email
        )

        db.session.add(customer)
        db.session.commit()

        return jsonify({
            "id": customer.id,
            "name": customer.name
        })

    except Exception:
        db.session.rollback()
        app.logger.exception("Unable to add customer from billing page")
        return jsonify({"error": "Unable to save customer. Please try again."}), 500
@app.route("/billing",methods=["GET","POST"])
@login_required
def billing():
    if request.method=="POST":
        try:
            kind=request.form.get("kind","normal"); discount=Decimal(request.form.get("discount","0"))
            ids=request.form.getlist("product_id[]"); quantities=request.form.getlist("qty[]")
            if not ids: raise ValueError("Add at least one product.")
            data=[]; subtotal=Decimal("0"); tax=Decimal("0")
            for pid,qt in zip(ids,quantities):
                p=Product.query.get(int(pid)); qty=int(qt)
                if not p or not p.active or qty<1 or qty>p.stock: raise ValueError("Invalid quantity or insufficient stock.")
                line=p.price*qty; gst=(line*p.gst/100) if kind=="gst" else Decimal("0")
                data.append((p,qty,line,gst)); subtotal+=line; tax+=gst
            if discount<0 or discount>subtotal: raise ValueError("Discount must be between zero and subtotal.")
            cid=request.form.get("customer_id") or None
            inv=Invoice(number="PS-"+datetime.now().strftime("%y%m%d%H%M%S%f"),customer_id=int(cid) if cid else None,user_id=current_user.id,kind=kind,subtotal=subtotal,discount=discount,tax=tax,total=subtotal-discount+tax)
            db.session.add(inv)
            for p,qty,line,gst in data:
                p.stock-=qty; db.session.add(Item(invoice=inv,product_id=p.id,name=p.name,qty=qty,price=p.price,gst=p.gst if kind=="gst" else 0,amount=line+gst))
            db.session.commit(); return redirect(url_for("invoice",iid=inv.id))
        except Exception as e: db.session.rollback(); flash("Bill failed: "+str(e),"danger"); return redirect(url_for("billing"))
    return render_template("billing.html",products=Product.query.filter(Product.active.is_(True),Product.stock>0).all(),customers=Customer.query.all())
@app.route("/invoices")
@login_required
def invoices(): return render_template("invoices.html",invoices=Invoice.query.order_by(Invoice.created.desc()).limit(250).all())
@app.route("/invoice/<int:iid>")
@login_required
def invoice(iid):
    return render_template(
        "invoice.html",
        inv=Invoice.query.get_or_404(iid)
    )


def create_invoice_pdf(inv):
    out = BytesIO()
    doc = SimpleDocTemplate(
        out,
        pagesize=A4,
        leftMargin=18*mm,
        rightMargin=18*mm
    )

    st = getSampleStyleSheet()

    story = [
        Paragraph("SRI VENKATESHWARA PROVISION STORE", st["Title"]),
        Paragraph("Invoice " + inv.number, st["Heading2"]),
        Paragraph(inv.created.strftime("%d %b %Y %I:%M %p"), st["Normal"]),
        Paragraph(
            "Customer: " + (inv.customer.name if inv.customer else "Walk-in"),
            st["Normal"]
        ),
        Spacer(1, 8*mm)
    ]

    rows = [
        ["Product", "Qty", "Price", "GST %", "Amount"]
    ] + [
        [x.name, str(x.qty), f"Rs. {x.price}", str(x.gst), f"Rs. {x.amount}"]
        for x in inv.items
    ]

    rows += [
        ["", "", "", "Subtotal", f"Rs. {inv.subtotal}"],
        ["", "", "", "Discount", f"Rs. {inv.discount}"],
        ["", "", "", "GST", f"Rs. {inv.tax}"],
        ["", "", "", "TOTAL", f"Rs. {inv.total}"]
    ]

    t = Table(
        rows,
        colWidths=[65*mm, 18*mm, 30*mm, 22*mm, 38*mm],
        repeatRows=1
    )

    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#176b55")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), .4, colors.lightgrey),
        ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
        ("PADDING", (0, 0), (-1, -1), 7)
    ]))

    story += [
        t,
        Spacer(1, 8*mm),
        Paragraph("Thank you for shopping with us!", st["Italic"])
    ]

    doc.build(story)
    return out.getvalue()


@app.route("/invoice/<int:iid>/pdf")
@login_required
def pdf(iid):
    inv = Invoice.query.get_or_404(iid)
    pdf_bytes = create_invoice_pdf(inv)

    return send_file(
        BytesIO(pdf_bytes),
        as_attachment=True,
        download_name=inv.number + ".pdf",
        mimetype="application/pdf"
    )


@app.route("/invoice/<int:iid>/email", methods=["POST"])
@login_required
def email_invoice(iid):
    inv = Invoice.query.get_or_404(iid)

    recipient = (
        inv.customer.email.strip()
        if inv.customer and inv.customer.email
        else ""
    )

    api_key = os.getenv("BREVO_API_KEY")
    sender = os.getenv("BREVO_SENDER")
    sender_name = os.getenv("BREVO_SENDER_NAME", "Sri Venkateshwara Provision Store")

    if not recipient:
        flash("Customer email address is missing.", "danger")
        return redirect(url_for("invoice", iid=iid))

    if not api_key or not sender:
        flash("Brevo email settings are missing. Check your .env file.", "danger")
        return redirect(url_for("invoice", iid=iid))

    pdf_bytes = create_invoice_pdf(inv)

    payload = {
        "sender": {
            "name": sender_name,
            "email": sender
        },
        "to": [
            {
                "email": recipient,
                "name": inv.customer.name
            }
        ],
        "subject": f"Sri Venkateshwara Provision Store - Invoice  {inv.number}",
        "textContent": (
            f"Hello {inv.customer.name},\n\n"
            f"Thank you for shopping with us.\n"
            f"Your invoice {inv.number} is attached.\n"
            f"Total amount: Rs. {inv.total}\n\n"
            "Thank you!"
        ),
        "attachment": [
            {
                "name": inv.number + ".pdf",
                "content": base64.b64encode(pdf_bytes).decode("ascii")
            }
        ]
    }

    try:
        response = requests.post(
            "https://api.brevo.com/v3/smtp/email",
            headers={
                "accept": "application/json",
                "api-key": api_key,
                "content-type": "application/json"
            },
            json=payload,
            timeout=20
        )

        if response.ok:
            flash("Invoice emailed successfully!", "success")
        else:
            app.logger.error(
                "Brevo email failed: %s %s",
                response.status_code,
                response.text
            )
            flash("Email could not be sent. Check Brevo configuration.", "danger")

    except requests.RequestException:
        app.logger.exception("Brevo email request failed")
        flash("Unable to connect to the email service. Please try again.", "danger")

    return redirect(url_for("invoice", iid=iid))
@app.route("/reports")
@login_required
def reports():
    start=request.args.get("start",date.today().replace(day=1).isoformat()); end=request.args.get("end",date.today().isoformat())
    try: a=datetime.strptime(start,"%Y-%m-%d"); b=datetime.strptime(end,"%Y-%m-%d").replace(hour=23,minute=59,second=59)
    except ValueError: flash("Invalid dates.","danger"); return redirect(url_for("reports"))
    sales=Invoice.query.filter(Invoice.created>=a,Invoice.created<=b).order_by(Invoice.created.desc()).all()
    total=sum((Decimal(x.total) for x in sales),Decimal("0"))
    low=Product.query.filter(Product.active.is_(True),Product.stock<=Product.low_stock).all()
    return render_template("reports.html",sales=sales,total=total,start=start,end=end,low=low)
@app.route("/staff",methods=["GET","POST"])
@admin
def staff():
    if request.method=="POST":
        name=request.form["username"].strip(); pw=request.form["password"]
        if len(name)<3 or len(pw)<8: flash("Use username 3+ characters and password 8+ characters.","danger")
        elif User.query.filter_by(username=name).first(): flash("Username already exists.","danger")
        else:
            u=User(username=name,role="staff"); u.set_password(pw); db.session.add(u); db.session.commit(); flash("Staff account created.","success")
        return redirect(url_for("staff"))
    return render_template("staff.html",users=User.query.all())
@app.route("/staff/<int:uid>/toggle",methods=["POST"])
@admin
def toggle(uid):
    u=User.query.get_or_404(uid)
    if u.id!=current_user.id: u.active=not u.active; db.session.commit()
    return redirect(url_for("staff"))
@app.errorhandler(403)
def denied(e): return render_template("error.html"),403
with app.app_context(): db.create_all()
if __name__=="__main__":
    print(app.url_map)
    app.run(debug=True)
