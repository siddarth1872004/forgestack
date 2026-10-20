from datetime import datetime, timedelta
from decimal import Decimal
from sqlalchemy.orm import Session
from .models import RawMaterial, RawMaterialCategory, Supplier, Product, ProductionOrder, MaterialConsumption, InventoryTransaction, User

def money_decimal(v):
    return Decimal(str(v))

def create_transaction(db, *, item_type, item_id, item_name, transaction_type, quantity, reference=None, note=None):
    tx = InventoryTransaction(item_type=item_type, item_id=item_id, item_name=item_name, transaction_type=transaction_type,
                              quantity=quantity, reference=reference, note=note)
    db.add(tx)
    return tx

def seed_demo(db: Session):
    if db.query(User).count():
        return
    # Local-only demo credentials; this mode must never be enabled in production.
    db.add(User(username="admin", password_hash="admin123", role="admin"))
    cats = {}
    for name in ["Metals", "Polymers", "Packaging", "Electrical"]:
        c = RawMaterialCategory(name=name); db.add(c); cats[name] = c
    suppliers = [
        Supplier(name="Southern Alloy Works", contact="+91 98765 12001", email="orders@southernalloy.example"),
        Supplier(name="Chennai Polymer Supply", contact="+91 98765 12002", email="sales@chennaipolymer.example"),
        Supplier(name="Prime Pack Industries", contact="+91 98765 12003", email="orders@primepack.example"),
    ]
    db.add_all(suppliers); db.flush()
    materials = [
        RawMaterial(material_code="RM-AL-001", name="Aluminium Sheet 2mm", unit="kg", quantity=Decimal("84"), min_stock=Decimal("100"), category=cats["Metals"], supplier=suppliers[0]),
        RawMaterial(material_code="RM-ST-002", name="Stainless Steel Rod 8mm", unit="kg", quantity=Decimal("240"), min_stock=Decimal("120"), category=cats["Metals"], supplier=suppliers[0]),
        RawMaterial(material_code="RM-PP-003", name="Polypropylene Pellets", unit="kg", quantity=Decimal("410"), min_stock=Decimal("200"), category=cats["Polymers"], supplier=suppliers[1]),
        RawMaterial(material_code="RM-PA-004", name="Polyamide Granules", unit="kg", quantity=Decimal("72"), min_stock=Decimal("80"), category=cats["Polymers"], supplier=suppliers[1]),
        RawMaterial(material_code="RM-BOX-005", name="Corrugated Carton", unit="units", quantity=Decimal("620"), min_stock=Decimal("250"), category=cats["Packaging"], supplier=suppliers[2]),
        RawMaterial(material_code="RM-LBL-006", name="Product Label Roll", unit="rolls", quantity=Decimal("36"), min_stock=Decimal("15"), category=cats["Packaging"], supplier=suppliers[2]),
    ]
    db.add_all(materials)
    products = [
        Product(product_code="FG-FAN-101", name="Industrial Cooling Fan 120mm", quantity=Decimal("148"), min_stock=Decimal("60")),
        Product(product_code="FG-PMP-202", name="Compact Water Pump 1HP", quantity=Decimal("46"), min_stock=Decimal("30")),
        Product(product_code="FG-VAL-303", name="Stainless Control Valve", quantity=Decimal("82"), min_stock=Decimal("25")),
    ]
    db.add_all(products); db.flush()
    now = datetime.utcnow()
    orders = [
        ProductionOrder(order_code="PO-2026-0142", product=products[0], quantity=Decimal("60"), status="In Progress", created_at=now-timedelta(hours=6), started_at=now-timedelta(hours=3)),
        ProductionOrder(order_code="PO-2026-0141", product=products[1], quantity=Decimal("24"), status="Completed", created_at=now-timedelta(days=1, hours=3), started_at=now-timedelta(days=1, hours=2), completed_at=now-timedelta(days=1)),
        ProductionOrder(order_code="PO-2026-0143", product=products[2], quantity=Decimal("40"), status="Pending", created_at=now-timedelta(hours=1)),
    ]
    db.add_all(orders); db.flush()
    db.add_all([
        MaterialConsumption(production_order=orders[1], material=materials[1], quantity=Decimal("18"), consumed_at=now-timedelta(days=1)),
        MaterialConsumption(production_order=orders[1], material=materials[2], quantity=Decimal("10"), consumed_at=now-timedelta(days=1)),
    ])
    db.add_all([
        create_transaction(db, item_type="Raw Material", item_id=materials[0].id, item_name=materials[0].name, transaction_type="Stock In", quantity=Decimal("120"), note="Opening stock"),
        create_transaction(db, item_type="Raw Material", item_id=materials[1].id, item_name=materials[1].name, transaction_type="Stock In", quantity=Decimal("260"), note="Opening stock"),
        create_transaction(db, item_type="Raw Material", item_id=materials[0].id, item_name=materials[0].name, transaction_type="Stock Out", quantity=Decimal("36"), reference="PO-2026-0139", note="Production issue"),
        create_transaction(db, item_type="Raw Material", item_id=materials[1].id, item_name=materials[1].name, transaction_type="Stock Out", quantity=Decimal("18"), reference="PO-2026-0141", note="Production issue"),
        create_transaction(db, item_type="Finished Good", item_id=products[1].id, item_name=products[1].name, transaction_type="Stock In", quantity=Decimal("24"), reference="PO-2026-0141", note="Production completed"),
    ])
    db.commit()

def dashboard(db: Session):
    materials = db.query(RawMaterial).all()
    products = db.query(Product).all()
    active = db.query(ProductionOrder).filter(ProductionOrder.status.in_(["Pending", "In Progress"])).count()
    completed = db.query(ProductionOrder).filter(ProductionOrder.status == "Completed").order_by(ProductionOrder.completed_at.desc()).limit(5).all()
    txs = db.query(InventoryTransaction).order_by(InventoryTransaction.created_at.desc()).limit(8).all()
    return {"total_materials": len(materials), "low_stock": sum(1 for m in materials if m.quantity <= m.min_stock),
            "finished_qty": sum(float(p.quantity) for p in products), "active_orders": active, "completed": completed, "transactions": txs}

def complete_order(db: Session, order: ProductionOrder):
    if order.status == "Completed":
        raise ValueError("Production order is already completed.")
    if not order.consumptions:
        raise ValueError("Issue at least one raw material before completing production.")
    order.status = "Completed"; order.completed_at = datetime.utcnow()
    product = order.product
    product.quantity = Decimal(product.quantity) + Decimal(order.quantity)
    create_transaction(db, item_type="Finished Good", item_id=product.id, item_name=product.name, transaction_type="Stock In",
                       quantity=order.quantity, reference=order.order_code, note="Production completed")
    db.commit(); db.refresh(order)

def consume_material(db: Session, order: ProductionOrder, material: RawMaterial, quantity: Decimal):
    if order.status == "Completed": raise ValueError("Cannot consume material for a completed order.")
    if quantity <= 0: raise ValueError("Consumption quantity must be greater than zero.")
    if material.quantity < quantity:
        raise ValueError(f"Insufficient stock for {material.name}. Available: {material.quantity:g} {material.unit}.")
    material.quantity = Decimal(material.quantity) - quantity
    db.add(MaterialConsumption(production_order=order, material=material, quantity=quantity))
    create_transaction(db, item_type="Raw Material", item_id=material.id, item_name=material.name, transaction_type="Stock Out",
                       quantity=quantity, reference=order.order_code, note="Material consumed for production")
    db.commit(); db.refresh(order)
