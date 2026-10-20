from datetime import datetime, date
from decimal import Decimal, InvalidOperation
from pathlib import Path
import os
import secrets
from fastapi import FastAPI, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_, desc, func
from .db import engine
from .db import init_db, get_db, SessionLocal
from .models import User, RawMaterial, RawMaterialCategory, Supplier, Product, ProductionOrder, MaterialConsumption, InventoryTransaction
from .services import seed_demo, dashboard, consume_material, complete_order, create_transaction

BASE = Path(__file__).parent

def verify_password(password: str, stored_hash: str) -> bool:
    # Accept PBKDF2-SHA256 hashes. Legacy plaintext is permitted only in opt-in demo mode.
    if stored_hash.startswith("pbkdf2_sha256$"):
        try:
            import hashlib, hmac, base64
            _, rounds, salt, digest = stored_hash.split("$", 3)
            actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(rounds))
            return hmac.compare_digest(base64.urlsafe_b64encode(actual).decode().rstrip("="), digest)
        except (ValueError, TypeError):
            return False
    return os.getenv("SEED_DEMO_DATA", "").lower() in {"1", "true", "yes"} and secrets.compare_digest(stored_hash, password)

app = FastAPI(title="ForgeStock Inventory Management System", version="1.1.1")
if os.getenv("VERCEL") and not os.getenv("DATABASE_URL"):
    @app.on_event("startup")
    def require_database_for_vercel():
        raise RuntimeError("DATABASE_URL is required on Vercel. Configure the Supabase PostgreSQL connection string.")

app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
templates = Jinja2Templates(directory=str(BASE / "templates"))

def hash_password(password: str, *, salt: str | None = None, rounds: int = 310_000) -> str:
    """Return a versioned PBKDF2-SHA256 password hash."""
    import base64, hashlib
    salt = salt or secrets.token_urlsafe(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), rounds)
    return f"pbkdf2_sha256${rounds}${salt}${base64.urlsafe_b64encode(digest).decode().rstrip('=')}"

@app.on_event("startup")
def startup():
    if os.getenv("VERCEL") and (not os.getenv("SESSION_SECRET") or os.getenv("SESSION_SECRET") == "local-development-only-change-this-secret"):
        raise RuntimeError("Set SESSION_SECRET to a long random value in Vercel environment variables.")
    if os.getenv("VERCEL") and os.getenv("SEED_DEMO_DATA", "").lower() in {"1", "true", "yes"}:
        raise RuntimeError("SEED_DEMO_DATA is only for disposable local demos. Disable it on Vercel.")
    init_db()
    db = SessionLocal()
    try:
        if os.getenv("SEED_DEMO_DATA", "").lower() in {"1", "true", "yes"}:
            seed_demo(db)
        # Lookup categories are reference data required by the existing material form.
        for category_name in ("Metals", "Polymers", "Packaging", "Electrical"):
            if not db.query(RawMaterialCategory).filter_by(name=category_name).first():
                db.add(RawMaterialCategory(name=category_name))
        # Secure first-admin provisioning: configure these only in server-side env vars.
        # Never create a predictable production password or expose this workflow publicly.
        admin_username = os.getenv("ADMIN_USERNAME", "").strip()
        admin_password = os.getenv("ADMIN_PASSWORD", "")
        if admin_username and admin_password:
            if len(admin_password) < 12:
                raise RuntimeError("ADMIN_PASSWORD must be at least 12 characters.")
            existing = db.query(User).filter_by(username=admin_username).first()
            if not existing:
                db.add(User(username=admin_username, password_hash=hash_password(admin_password), role="admin", is_active=True))
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

def auth(request: Request):
    if not request.session.get("user"):
        raise HTTPException(status_code=401, detail="Authentication required")

from starlette.middleware.sessions import SessionMiddleware
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SESSION_SECRET", "local-development-only-change-this-secret"),
    https_only=os.getenv("COOKIE_SECURE", "false").lower() in {"1", "true", "yes"},
    same_site="lax",
)

@app.get("/api/health")
def health():
    configured = bool(os.getenv("DATABASE_URL", "").strip())
    try:
        from sqlalchemy import text
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return {"status": "ok", "database_configured": configured, "database_connected": True,
                "mode": "supabase" if configured else "local-sqlite"}
    except Exception:
        # Deliberately avoid returning credentials, hostnames, or raw DB errors.
        return JSONResponse({"status": "error", "database_configured": configured,
                             "database_connected": False, "mode": "supabase" if configured else "local-sqlite"},
                            status_code=503)

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    if not request.session.get("user"):
        return RedirectResponse("/login")
    return templates.TemplateResponse("index.html", {"request": request, "user": request.session.get("user")})

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    demo_mode = os.getenv("SEED_DEMO_DATA", "").lower() in {"1", "true", "yes"}
    return templates.TemplateResponse("login.html", {"request": request, "error": None, "demo_mode": demo_mode})

@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == username, User.is_active == True).first()
    if not user or not verify_password(password, user.password_hash):
        demo_mode = os.getenv("SEED_DEMO_DATA", "").lower() in {"1", "true", "yes"}
        return templates.TemplateResponse("login.html", {"request": request, "error": "Invalid username or password.", "demo_mode": demo_mode}, status_code=401)
    request.session["user"] = {"id": user.id, "username": user.username, "role": user.role}
    return RedirectResponse("/", status_code=303)

@app.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)

def serialize_material(m):
    return {"id": m.id, "code": m.material_code, "name": m.name, "category": m.category.name if m.category else "Uncategorized", "unit": m.unit,
            "quantity": float(m.quantity), "min_stock": float(m.min_stock), "supplier": m.supplier.name if m.supplier else "—", "status": "Low Stock" if m.quantity <= m.min_stock else "In Stock"}
def serialize_product(p):
    return {"id": p.id, "code": p.product_code, "name": p.name, "unit": p.unit, "quantity": float(p.quantity), "min_stock": float(p.min_stock), "status": "Low Stock" if p.quantity <= p.min_stock else "In Stock"}
def serialize_order(o):
    return {"id": o.id, "code": o.order_code, "product": o.product.name, "product_id": o.product_id, "quantity": float(o.quantity), "status": o.status,
            "created_at": o.created_at.isoformat(), "started_at": o.started_at.isoformat() if o.started_at else None, "completed_at": o.completed_at.isoformat() if o.completed_at else None,
            "consumptions": [{"id": c.id, "material": c.material.name, "material_id": c.material_id, "quantity": float(c.quantity), "unit": c.material.unit} for c in o.consumptions]}
def serialize_tx(t):
    return {"id": t.id, "item_type": t.item_type, "item_name": t.item_name, "type": t.transaction_type, "quantity": float(t.quantity), "reference": t.reference, "note": t.note, "created_at": t.created_at.isoformat()}

@app.get("/api/dashboard")
def api_dashboard(request: Request, db: Session = Depends(get_db)):
    auth(request); d = dashboard(db)
    return {"total_materials": d["total_materials"], "low_stock": d["low_stock"], "finished_qty": d["finished_qty"], "active_orders": d["active_orders"],
            "completed": [serialize_order(o) for o in d["completed"]], "transactions": [serialize_tx(t) for t in d["transactions"]]}

@app.get("/api/materials")
def materials(request: Request, q: str = "", category: str = "", db: Session = Depends(get_db)):
    auth(request); query = db.query(RawMaterial).options(joinedload(RawMaterial.category), joinedload(RawMaterial.supplier)).order_by(RawMaterial.name)
    if q: query = query.filter(or_(RawMaterial.name.ilike(f"%{q}%"), RawMaterial.material_code.ilike(f"%{q}%")))
    if category: query = query.join(RawMaterialCategory).filter(RawMaterialCategory.name == category)
    return {"items": [serialize_material(m) for m in query.all()], "categories": [c.name for c in db.query(RawMaterialCategory).order_by(RawMaterialCategory.name).all()]}

@app.post("/api/materials")
def add_material(request: Request, payload: dict, db: Session = Depends(get_db)):
    auth(request)
    try:
        qty, minimum = Decimal(str(payload["quantity"])), Decimal(str(payload["min_stock"]))
        if qty < 0 or minimum < 0: raise ValueError()
    except (KeyError, InvalidOperation, ValueError): raise HTTPException(400, "Quantity values must be valid non-negative numbers.")
    if db.query(RawMaterial).filter(RawMaterial.material_code == payload["code"]).first(): raise HTTPException(409, "Material code already exists.")
    category = db.query(RawMaterialCategory).filter_by(name=payload["category"]).first()
    if not category: raise HTTPException(400, "Unknown category.")
    supplier = db.query(Supplier).filter_by(id=payload.get("supplier_id")).first() if payload.get("supplier_id") else None
    m = RawMaterial(material_code=payload["code"].strip(), name=payload["name"].strip(), unit=payload["unit"], quantity=qty, min_stock=minimum, category=category, supplier=supplier)
    db.add(m); db.flush()
    if qty: create_transaction(db, item_type="Raw Material", item_id=m.id, item_name=m.name, transaction_type="Stock In", quantity=qty, note="Opening stock")
    db.commit(); return serialize_material(m)

@app.put("/api/materials/{material_id}")
def edit_material(request: Request, material_id: int, payload: dict, db: Session = Depends(get_db)):
    auth(request); m = db.query(RawMaterial).get(material_id)
    if not m: raise HTTPException(404, "Material not found.")
    try: minimum = Decimal(str(payload["min_stock"]))
    except Exception: raise HTTPException(400, "Minimum stock must be numeric.")
    if minimum < 0: raise HTTPException(400, "Minimum stock cannot be negative.")
    m.name = payload["name"].strip(); m.unit = payload["unit"]; m.min_stock = minimum
    db.commit(); db.refresh(m); return serialize_material(m)

@app.delete("/api/materials/{material_id}")
def delete_material(request: Request, material_id: int, db: Session = Depends(get_db)):
    auth(request); m = db.query(RawMaterial).get(material_id)
    if not m: raise HTTPException(404, "Material not found.")
    if db.query(MaterialConsumption).filter_by(material_id=material_id).count(): raise HTTPException(409, "Material has production history and cannot be deleted.")
    db.delete(m); db.commit(); return {"ok": True}

@app.get("/api/inventory")
def inventory(request: Request, q: str = "", db: Session = Depends(get_db)):
    auth(request); mats = db.query(RawMaterial).options(joinedload(RawMaterial.category)).all(); prods = db.query(Product).all()
    rows = [{"type": "Raw Material", **serialize_material(m)} for m in mats] + [{"type": "Finished Good", **serialize_product(p)} for p in prods]
    if q: rows = [r for r in rows if q.lower() in (r["name"] + " " + r["code"]).lower()]
    return {"items": rows}

@app.get("/api/transactions")
def transactions(request: Request, q: str = "", db: Session = Depends(get_db)):
    auth(request); query = db.query(InventoryTransaction).order_by(desc(InventoryTransaction.created_at))
    if q: query = query.filter(or_(InventoryTransaction.item_name.ilike(f"%{q}%"), InventoryTransaction.reference.ilike(f"%{q}%")))
    return {"items": [serialize_tx(t) for t in query.limit(200).all()]}

@app.get("/api/products")
def products(request: Request, db: Session = Depends(get_db)):
    auth(request); return {"items": [serialize_product(p) for p in db.query(Product).order_by(Product.name).all()]}

@app.get("/api/orders")
def orders(request: Request, status: str = "", q: str = "", db: Session = Depends(get_db)):
    auth(request); query = db.query(ProductionOrder).options(joinedload(ProductionOrder.product), joinedload(ProductionOrder.consumptions).joinedload(MaterialConsumption.material)).order_by(desc(ProductionOrder.created_at))
    if status: query = query.filter(ProductionOrder.status == status)
    if q: query = query.join(Product).filter(or_(ProductionOrder.order_code.ilike(f"%{q}%"), Product.name.ilike(f"%{q}%")))
    return {"items": [serialize_order(o) for o in query.all()]}

@app.post("/api/orders")
def create_order(request: Request, payload: dict, db: Session = Depends(get_db)):
    auth(request)
    try: qty = Decimal(str(payload["quantity"]))
    except Exception: raise HTTPException(400, "Quantity must be numeric.")
    if qty <= 0: raise HTTPException(400, "Production quantity must be greater than zero.")
    product = db.query(Product).get(payload.get("product_id"))
    if not product: raise HTTPException(404, "Product not found.")
    count = db.query(ProductionOrder).count() + 142
    o = ProductionOrder(order_code=f"PO-{datetime.utcnow().year}-{count:04d}", product=product, quantity=qty)
    db.add(o); db.commit(); db.refresh(o); return serialize_order(o)

@app.post("/api/orders/{order_id}/start")
def start_order(request: Request, order_id: int, db: Session = Depends(get_db)):
    auth(request); o = db.query(ProductionOrder).get(order_id)
    if not o: raise HTTPException(404, "Order not found.")
    if o.status != "Pending": raise HTTPException(400, "Only pending orders can be started.")
    o.status = "In Progress"; o.started_at = datetime.utcnow(); db.commit(); return serialize_order(o)

@app.post("/api/orders/{order_id}/complete")
def finish_order(request: Request, order_id: int, db: Session = Depends(get_db)):
    auth(request); o = db.query(ProductionOrder).options(joinedload(ProductionOrder.product), joinedload(ProductionOrder.consumptions)).get(order_id)
    if not o: raise HTTPException(404, "Order not found.")
    try: complete_order(db, o)
    except ValueError as e: raise HTTPException(400, str(e))
    return serialize_order(o)

@app.post("/api/orders/{order_id}/consume")
def consume(request: Request, order_id: int, payload: dict, db: Session = Depends(get_db)):
    auth(request); o = db.query(ProductionOrder).get(order_id)
    m = db.query(RawMaterial).get(payload.get("material_id"))
    if not o or not m: raise HTTPException(404, "Production order or material not found.")
    try: qty = Decimal(str(payload["quantity"]))
    except Exception: raise HTTPException(400, "Quantity must be numeric.")
    try: consume_material(db, o, m, qty)
    except ValueError as e: raise HTTPException(400, str(e))
    return {"ok": True, "material": serialize_material(m)}

@app.get("/api/consumptions")
def consumptions(request: Request, q: str = "", db: Session = Depends(get_db)):
    auth(request); query = db.query(MaterialConsumption).options(joinedload(MaterialConsumption.material), joinedload(MaterialConsumption.production_order)).order_by(desc(MaterialConsumption.consumed_at))
    rows = query.limit(300).all()
    if q: rows = [r for r in rows if q.lower() in (r.material.name + " " + r.production_order.order_code).lower()]
    return {"items": [{"id": r.id, "order": r.production_order.order_code, "material": r.material.name, "quantity": float(r.quantity), "unit": r.material.unit, "consumed_at": r.consumed_at.isoformat()} for r in rows]}

@app.get("/api/reports")
def reports(request: Request, kind: str="inventory", q: str="", from_date: str="", to_date: str="", db: Session=Depends(get_db)):
    auth(request)
    start = datetime.fromisoformat(from_date) if from_date else None
    end = datetime.fromisoformat(to_date).replace(hour=23, minute=59, second=59) if to_date else None
    if kind == "production":
        query = db.query(ProductionOrder).options(joinedload(ProductionOrder.product)).order_by(desc(ProductionOrder.created_at))
        if start: query = query.filter(ProductionOrder.created_at >= start)
        if end: query = query.filter(ProductionOrder.created_at <= end)
        if q: query = query.join(Product).filter(or_(ProductionOrder.order_code.ilike(f"%{q}%"), Product.name.ilike(f"%{q}%")))
        return {"items": [serialize_order(o) for o in query.all()]}
    if kind == "consumption":
        query = db.query(MaterialConsumption).options(joinedload(MaterialConsumption.material), joinedload(MaterialConsumption.production_order)).order_by(desc(MaterialConsumption.consumed_at))
        if start: query = query.filter(MaterialConsumption.consumed_at >= start)
        if end: query = query.filter(MaterialConsumption.consumed_at <= end)
        rows = query.all()
        if q: rows = [r for r in rows if q.lower() in (r.material.name + " " + r.production_order.order_code).lower()]
        return {"items": [{"id": r.id, "order": r.production_order.order_code, "material": r.material.name, "quantity": float(r.quantity), "unit": r.material.unit, "consumed_at": r.consumed_at.isoformat()} for r in rows]}
    return inventory(request, q=q, db=db)

# Supplier master-data endpoints used by the existing Suppliers navigation.
def serialize_supplier(s):
    return {"id": s.id, "name": s.name, "contact": s.contact or "", "email": s.email or "",
            "materials_count": len(s.materials)}

@app.get("/api/suppliers")
def list_suppliers(request: Request, q: str = "", db: Session = Depends(get_db)):
    auth(request)
    query = db.query(Supplier).order_by(Supplier.name)
    if q:
        query = query.filter(or_(Supplier.name.ilike(f"%{q}%"), Supplier.contact.ilike(f"%{q}%"), Supplier.email.ilike(f"%{q}%")))
    return {"items": [serialize_supplier(s) for s in query.all()]}

@app.post("/api/suppliers")
def add_supplier(request: Request, payload: dict, db: Session = Depends(get_db)):
    auth(request)
    name = str(payload.get("name", "")).strip()
    if not name:
        raise HTTPException(400, "Supplier name is required.")
    if len(name) > 120:
        raise HTTPException(400, "Supplier name must be 120 characters or fewer.")
    email = str(payload.get("email", "")).strip() or None
    contact = str(payload.get("contact", "")).strip() or None
    if email and (len(email) > 120 or "@" not in email):
        raise HTTPException(400, "Enter a valid supplier email address.")
    supplier = Supplier(name=name, contact=contact, email=email)
    db.add(supplier)
    db.commit()
    db.refresh(supplier)
    return serialize_supplier(supplier)

@app.put("/api/suppliers/{supplier_id}")
def edit_supplier(request: Request, supplier_id: int, payload: dict, db: Session = Depends(get_db)):
    auth(request)
    supplier = db.get(Supplier, supplier_id)
    if not supplier:
        raise HTTPException(404, "Supplier not found.")
    name = str(payload.get("name", "")).strip()
    email = str(payload.get("email", "")).strip() or None
    if not name or len(name) > 120:
        raise HTTPException(400, "Supplier name is required and must be 120 characters or fewer.")
    if email and (len(email) > 120 or "@" not in email):
        raise HTTPException(400, "Enter a valid supplier email address.")
    supplier.name = name
    supplier.contact = str(payload.get("contact", "")).strip() or None
    supplier.email = email
    db.commit()
    db.refresh(supplier)
    return serialize_supplier(supplier)

@app.delete("/api/suppliers/{supplier_id}")
def delete_supplier(request: Request, supplier_id: int, db: Session = Depends(get_db)):
    auth(request)
    supplier = db.get(Supplier, supplier_id)
    if not supplier:
        raise HTTPException(404, "Supplier not found.")
    if db.query(RawMaterial).filter_by(supplier_id=supplier_id).count():
        raise HTTPException(409, "This supplier is assigned to raw materials. Reassign them before deleting.")
    db.delete(supplier)
    db.commit()
    return {"ok": True}

# Finished-goods master-data endpoints complete the existing product workflow.
@app.post("/api/products")
def add_product(request: Request, payload: dict, db: Session = Depends(get_db)):
    auth(request)
    code = str(payload.get("code", "")).strip()
    name = str(payload.get("name", "")).strip()
    unit = str(payload.get("unit", "units")).strip() or "units"
    try:
        qty = Decimal(str(payload.get("quantity", 0)))
        minimum = Decimal(str(payload.get("min_stock", 0)))
        if not code or not name or len(code) > 30 or len(name) > 120 or qty < 0 or minimum < 0:
            raise ValueError()
    except (InvalidOperation, ValueError):
        raise HTTPException(400, "Enter a valid code, name and non-negative quantities.")
    if db.query(Product).filter_by(product_code=code).first():
        raise HTTPException(409, "Product code already exists.")
    product = Product(product_code=code, name=name, unit=unit[:20], quantity=qty, min_stock=minimum)
    db.add(product)
    db.flush()
    if qty:
        create_transaction(db, item_type="Finished Good", item_id=product.id, item_name=name,
                           transaction_type="Stock In", quantity=qty, note="Opening stock")
    db.commit()
    db.refresh(product)
    return serialize_product(product)

@app.put("/api/products/{product_id}")
def edit_product(request: Request, product_id: int, payload: dict, db: Session = Depends(get_db)):
    auth(request)
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(404, "Product not found.")
    name = str(payload.get("name", "")).strip()
    unit = str(payload.get("unit", product.unit)).strip()
    try:
        minimum = Decimal(str(payload.get("min_stock", product.min_stock)))
        if not name or len(name) > 120 or minimum < 0:
            raise ValueError()
    except (InvalidOperation, ValueError):
        raise HTTPException(400, "Enter a product name and non-negative minimum stock.")
    product.name = name
    product.unit = unit[:20] or "units"
    product.min_stock = minimum
    db.commit()
    db.refresh(product)
    return serialize_product(product)

@app.delete("/api/products/{product_id}")
def delete_product(request: Request, product_id: int, db: Session = Depends(get_db)):
    auth(request)
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(404, "Product not found.")
    if db.query(ProductionOrder).filter_by(product_id=product_id).count():
        raise HTTPException(409, "This product has production history and cannot be deleted.")
    db.delete(product)
    db.commit()
    return {"ok": True}

@app.post("/api/stock-adjustments")
def stock_adjustment(request: Request, payload: dict, db: Session = Depends(get_db)):
    auth(request)
    item_type = str(payload.get("item_type", ""))
    transaction_type = str(payload.get("transaction_type", ""))
    if item_type not in {"Raw Material", "Finished Good"} or transaction_type not in {"Stock In", "Stock Out"}:
        raise HTTPException(400, "Choose a valid inventory item type and stock movement.")
    try:
        item_id = int(payload.get("item_id"))
        quantity = Decimal(str(payload.get("quantity")))
        if quantity <= 0:
            raise ValueError()
    except (TypeError, ValueError, InvalidOperation):
        raise HTTPException(400, "Quantity must be a positive number.")
    model = RawMaterial if item_type == "Raw Material" else Product
    item = db.get(model, item_id)
    if not item:
        raise HTTPException(404, "Inventory item not found.")
    current = Decimal(item.quantity)
    if transaction_type == "Stock Out" and quantity > current:
        raise HTTPException(400, f"Insufficient stock. Available: {current} {item.unit}.")
    item.quantity = current + quantity if transaction_type == "Stock In" else current - quantity
    create_transaction(db, item_type=item_type, item_id=item.id, item_name=item.name,
                       transaction_type=transaction_type, quantity=quantity,
                       reference=str(payload.get("reference", "")).strip()[:50] or None,
                       note=str(payload.get("note", "")).strip()[:2000] or "Manual stock adjustment")
    db.commit()
    db.refresh(item)
    return {"ok": True, "item": serialize_material(item) if item_type == "Raw Material" else serialize_product(item)}

