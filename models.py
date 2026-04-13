from datetime import datetime

from sqlalchemy import Column, Integer, String, Text, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from database import Base


class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True, index=True)
    slug = Column(String, unique=True, index=True)
    title_ru = Column(String)
    title_kz = Column(String)
    img = Column(String)
    path = Column(String)
    parent_slug = Column(String, nullable=True)

    products = relationship("Product", back_populates="category")


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String)
    img = Column(String)
    description_ru = Column(Text, nullable=True)
    description_kz = Column(Text, nullable=True)
    material_ru = Column(String, nullable=True)
    material_kz = Column(String, nullable=True)
    size = Column(String, nullable=True)
    article = Column(String, nullable=True)
    in_stock = Column(Boolean, default=True)
    category_slug = Column(String, ForeignKey("categories.slug"))

    category = relationship("Category", back_populates="products")


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id"))
    product_title = Column(String)
    client_name = Column(String, nullable=True)
    client_phone = Column(String, nullable=True)
    message = Column(Text, nullable=True)
    status = Column(String, default="new")
    created_at = Column(String)


class Application(Base):
    __tablename__ = "applications"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    phone = Column(String, nullable=False)
    username = Column(String, nullable=True)
    comment = Column(Text, nullable=True)
    product_name = Column(String, nullable=False)
    article = Column(String, nullable=True)
    product_url = Column(String, nullable=True)
    status = Column(String, default="new")
    manager_id = Column(Integer, nullable=True)
    manager_name = Column(String, nullable=True)
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    updated_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    password = Column(String, nullable=False)
    phone = Column(String, nullable=True)