from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from database import Base, engine
from routerss import auth, categories, orders, products, applications

Base.metadata.create_all(bind=engine)

app = FastAPI(title="STEM Academia API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(products.router, prefix="/api/products", tags=["products"])
app.include_router(categories.router, prefix="/api/categories", tags=["categories"])
app.include_router(orders.router, prefix="/api/orders", tags=["orders"])
app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(applications.router, prefix="/api/applications", tags=["applications"])


@app.get("/")
def root():
    return {"message": "STEM Academia API работает"}