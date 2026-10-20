from datetime import datetime, date
from decimal import Decimal, InvalidOperation
from pathlib import Path
import os
from fastapi import FastAPI, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_, desc
from .db import init_db, get_db, SessionLocal
from .models import User, RawMaterial, RawMaterialCategory, Supplier, Product, ProductionOrder, MaterialConsumption, InventoryTransaction
from .services import seed_demo, dashboard, consume_material, complete_order, create_transaction

BASE = Path(__file__).parent

def verify_password(password: str, stored_hash: str) -> bool:
    # Accept plaintext seed credentials only when demo mode is explicitly enabled.
    if stored_hash.startswith("pbkdf2_sha256$"):
        try:
            import hashlib, hmac, base64
            _, rounds, salt, digest = stored_hash.split("$", 3)
            actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(rounds))
            return hmac.compare_digest(base64.urlsafe_b64encode(actual).decode().rstrip("="), digest)
        except (ValueError, TypeError):
            return False
    return os.getenv("SEED_DEMO_DATA", "").lower() in {"1", "true", "yes"} and stored_hash == password

app = FastAPI(title="ForgeStock Inventory Management System", version="1.1.0")
if os.getenv("VERCEL") and not os.getenv("DATABASE_URL"):
    @app.on_event("startup")
    def require_database_for_vercel():
        raise RuntimeError("DATABASE_URL is required on Vercel. Configure the Supabase PostgreSQL connection string.")

app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
templates = Jinja2Templates(directory=str(BASE / "templates"))

@app.on_event("startup")
def startup():
    init_db()
    # Sample content is opt-in. New production databases start empty.
    if os.getenv("SEED_DEMO_DATA", "").lower() in {"1", "true", "yes"}:
        db = SessionLocal()
        try:
            seed_demo(db)
        finally:
            db.close()

def auth(request: Request):
    if not request.session.get("user"):
        raise HTTPException(status_code=401, detail="Authentication required")

# Use a Vercel environment variable in production; the fallback is local-only.
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
    return {"status": "ok", "database_configured": configured, "mode": "supabase" if configured else "local-sqlite"}

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
