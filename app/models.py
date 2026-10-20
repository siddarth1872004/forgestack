from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(30), default="admin")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

class RawMaterialCategory(Base):
    __tablename__ = "raw_material_categories"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    materials: Mapped[list["RawMaterial"]] = relationship(back_populates="category")

class Supplier(Base):
    __tablename__ = "suppliers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    contact: Mapped[str | None] = mapped_column(String(120), nullable=True)
    email: Mapped[str | None] = mapped_column(String(120), nullable=True)
    materials: Mapped[list["RawMaterial"]] = relationship(back_populates="supplier")

class RawMaterial(Base):
    __tablename__ = "raw_materials"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    material_code: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    unit: Mapped[str] = mapped_column(String(20))
    quantity: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    min_stock: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    category_id: Mapped[int] = mapped_column(ForeignKey("raw_material_categories.id"))
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"), nullable=True)
    category: Mapped["RawMaterialCategory"] = relationship(back_populates="materials")
    supplier: Mapped["Supplier | None"] = relationship(back_populates="materials")
    consumptions: Mapped[list["MaterialConsumption"]] = relationship(back_populates="material")

class Product(Base):
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_code: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    unit: Mapped[str] = mapped_column(String(20), default="units")
    quantity: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    min_stock: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    orders: Mapped[list["ProductionOrder"]] = relationship(back_populates="product")

class ProductionOrder(Base):
    __tablename__ = "production_orders"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_code: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    quantity: Mapped[float] = mapped_column(Numeric(12, 2))
    status: Mapped[str] = mapped_column(String(30), default="Pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    product: Mapped["Product"] = relationship(back_populates="orders")
    consumptions: Mapped[list["MaterialConsumption"]] = relationship(back_populates="production_order", cascade="all, delete-orphan")

class MaterialConsumption(Base):
    __tablename__ = "material_consumptions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    production_order_id: Mapped[int] = mapped_column(ForeignKey("production_orders.id"))
    material_id: Mapped[int] = mapped_column(ForeignKey("raw_materials.id"))
    quantity: Mapped[float] = mapped_column(Numeric(12, 2))
    consumed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    production_order: Mapped["ProductionOrder"] = relationship(back_populates="consumptions")
    material: Mapped["RawMaterial"] = relationship(back_populates="consumptions")

class InventoryTransaction(Base):
    __tablename__ = "inventory_transactions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    item_type: Mapped[str] = mapped_column(String(30))
    item_id: Mapped[int] = mapped_column(Integer)
    item_name: Mapped[str] = mapped_column(String(120))
    transaction_type: Mapped[str] = mapped_column(String(30))
    quantity: Mapped[float] = mapped_column(Numeric(12, 2))
    reference: Mapped[str | None] = mapped_column(String(50), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
