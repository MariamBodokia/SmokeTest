import os
import time
import uuid
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

load_dotenv()

app = FastAPI(title="SmokeMonitor Demo Application", version="0.2.0")
admin_token = os.getenv("ADMIN_TOKEN", "local-admin-token")
faults: dict[str, Any] = {
    "http_500": False,
    "slow": False,
    "broken_ui": False,
    "out_of_stock": False,
}
products = [
    {"id": "aurora-mug", "name": "Aurora ceramic mug", "price": 24, "emoji": "☕", "tag": "Bestseller"},
    {"id": "orbit-bottle", "name": "Orbit travel bottle", "price": 38, "emoji": "◉", "tag": "New"},
    {"id": "luna-notebook", "name": "Luna dot notebook", "price": 16, "emoji": "✦", "tag": "Essential"},
]
orders_store: list[dict[str, Any]] = []


def correlation_id(request: Request) -> str:
    return request.headers.get("x-correlation-id", str(uuid.uuid4()))


def deliberate_failure(request: Request) -> JSONResponse | None:
    if faults["slow"]:
        time.sleep(3)
    if faults["http_500"]:
        return JSONResponse(
            status_code=500,
            content={"error": "deliberate demo failure", "correlationId": correlation_id(request)},
        )
    return None


@app.middleware("http")
async def add_correlation_id(request: Request, call_next):
    response = await call_next(request)
    response.headers["x-correlation-id"] = correlation_id(request)
    return response


def page(title: str, content: str) -> str:
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title>
<style>
:root{{font-family:Inter,system-ui,sans-serif;color:#14213d;background:#f6f8fc}}*{{box-sizing:border-box}}
body{{margin:0}}.nav{{padding:22px 7%;display:flex;justify-content:space-between;background:#fff;border-bottom:1px solid #e8ecf4}}
.brand{{font-weight:800;letter-spacing:-.03em}}a{{color:#4776e6;text-decoration:none}}.wrap{{max-width:1120px;margin:48px auto;padding:0 24px}}
.eyebrow{{color:#4776e6;font-weight:700;text-transform:uppercase;letter-spacing:.12em;font-size:12px}}
h1{{font-size:clamp(38px,5vw,62px);line-height:1.04;margin:14px 0}}h2{{margin:10px 0}}
.lead,.muted{{color:#64748b;line-height:1.6}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:20px}}
.card{{background:#fff;border:1px solid #e8ecf4;border-radius:20px;padding:24px;box-shadow:0 14px 40px #263b6510}}
.visual{{font-size:64px;text-align:center;padding:28px;background:linear-gradient(135deg,#4776e6,#8e54e9);border-radius:15px;color:#fff}}
button,.button{{display:inline-block;border:0;border-radius:9px;padding:12px 17px;background:#14213d;color:#fff;font-weight:700;cursor:pointer}}
.price{{font-size:24px;font-weight:800;margin:18px 0}}.tag{{color:#17834b;font-size:12px;font-weight:700;text-transform:uppercase}}
@media(max-width:700px){{.wrap{{margin-top:25px}}}}
</style></head><body><nav class="nav"><a class="brand" href="/">NORTHSTAR / SHOP</a>
<span><a href="/products">Catalog</a> &nbsp; <a href="/orders">Orders</a> &nbsp; <a href="/admin">Operations</a></span></nav>
{content}</body></html>"""


@app.get("/health")
async def health(request: Request):
    failure = deliberate_failure(request)
    if failure:
        return failure
    return {"status": "ok", "service": "demo-app", "version": "0.2.0", "correlationId": correlation_id(request)}


@app.get("/api/products")
async def product_api(request: Request):
    failure = deliberate_failure(request)
    if failure:
        return failure
    return {"products": products, "correlationId": correlation_id(request)}


@app.get("/api/orders")
async def orders_api(request: Request):
    failure = deliberate_failure(request)
    if failure:
        return failure
    return {"orders": orders_store, "correlationId": correlation_id(request)}


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    failure = deliberate_failure(request)
    if failure:
        return failure
    button = "" if faults["broken_ui"] else '<a class="button" id="checkout" href="/checkout">Explore the catalog</a>'
    return page("Northstar Shop | Demo", f"""<main class="wrap"><div class="grid" style="align-items:center">
<section><div class="eyebrow">Demo commerce experience</div><h1>Simple buying.<br><span style="color:#4776e6">Reliable delivery.</span></h1>
<p class="lead">A realistic storefront for validating smoke tests, monitoring, and incident response.</p>{button}</section>
<section class="card"><div class="visual">✦</div><h2>Northstar essentials</h2><p class="muted">Three thoughtfully designed products, ready to ship.</p></section>
</div></main>""")


@app.get("/products", response_class=HTMLResponse)
async def product_list(request: Request):
    failure = deliberate_failure(request)
    if failure:
        return failure
    cards = "".join(
        f'<article class="card" data-product="{p["id"]}"><div class="visual">{p["emoji"]}</div>'
        f'<span class="tag">{p["tag"]}</span><h2>{p["name"]}</h2><div class="price">${p["price"]}</div>'
        f'<a class="button" href="/products/{p["id"]}">View product</a></article>' for p in products
    )
    return page("Catalog | Northstar Shop", f'<main class="wrap"><div class="eyebrow">The collection</div>'
                f'<h1>Designed for daily rituals.</h1><p class="lead">Shop the Northstar collection.</p>'
                f'<section class="grid">{cards}</section></main>')


@app.get("/products/{product_id}", response_class=HTMLResponse)
async def product_detail(product_id: str):
    product = next((item for item in products if item["id"] == product_id), None)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    availability = "Out of stock" if faults["out_of_stock"] else "In stock · Ships today"
    return page(product["name"], f'<main class="wrap"><div class="card" style="max-width:720px">'
                f'<div class="visual">{product["emoji"]}</div><span class="tag">{product["tag"]}</span>'
                f'<h1>{product["name"]}</h1><div class="price">${product["price"]}</div>'
                f'<p class="lead">Thoughtfully made for a calmer, more reliable day.</p>'
                f'<p class="muted" id="availability">{availability}</p>'
                f'<a class="button" id="add-to-cart" href="/checkout">Add to cart</a></div></main>')


@app.get("/checkout", response_class=HTMLResponse)
async def checkout():
    return page("Checkout | Northstar Shop", """<main class="wrap"><div class="card" style="max-width:650px">
<div class="eyebrow">Secure checkout</div><h1>Almost there.</h1><p class="lead">Complete the demo order to test the full journey.</p>
<form id="checkout-form"><label>Name<br><input required name="name" style="padding:12px;width:100%;margin:8px 0 16px"></label>
<label>Email<br><input required type="email" name="email" style="padding:12px;width:100%;margin:8px 0 16px"></label>
<button>Place demo order</button></form><p id="result" class="muted"></p></div></main>
<script>document.querySelector('#checkout-form').onsubmit=async e=>{e.preventDefault();const r=await fetch('/api/orders',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(Object.fromEntries(new FormData(e.target)))});const d=await r.json();document.querySelector('#result').textContent=r.ok?'Order '+d.order.id+' confirmed.':'Unable to place order';}</script>""")


@app.post("/api/orders")
async def create_order(request: Request):
    failure = deliberate_failure(request)
    if failure:
        return failure
    body = await request.json()
    if not body.get("name") or not body.get("email"):
        raise HTTPException(status_code=422, detail="Name and email are required")
    order = {"id": f"order-{len(orders_store) + 1:03}", "status": "confirmed", "customer": body["name"]}
    orders_store.append(order)
    return {"order": order, "correlationId": correlation_id(request)}


@app.get("/orders", response_class=HTMLResponse)
async def orders_page():
    rows = "".join(f'<li><strong>{order["id"]}</strong> · {order["status"]}</li>' for order in orders_store)
    return page("Orders | Northstar Shop", f'<main class="wrap"><div class="eyebrow">Account</div><h1>Your orders</h1>'
                f'<div class="card"><ul id="orders">{rows or "<li>No orders yet.</li>"}</ul></div></main>')


@app.get("/admin", response_class=HTMLResponse)
async def admin_page():
    return page("SmokeMonitor | Operations", """<main class="wrap"><div class="eyebrow">POC control center</div>
<h1>Failure injection lab</h1><p class="lead">Create controlled incidents and watch Jenkins classify the evidence.</p>
<input id="token" type="password" placeholder="Admin token" style="padding:12px;min-width:280px">
<button onclick="resetFaults()">Reset all faults</button><p id="message"></p><section id="faults" class="grid"></section></main>
<script>
const definitions={http_500:['HTTP 500 responses','Make API and health checks fail.'],slow:['Slow responses','Add a three-second delay to requests.'],broken_ui:['Broken checkout UI','Remove the checkout button.'],out_of_stock:['Out of stock','Show products as unavailable.']};
const token=document.querySelector('#token');token.value=localStorage.getItem('adminToken')||'';
function show(m){document.querySelector('#message').textContent=m}
async function call(path,method){const r=await fetch(path,{method,headers:{'X-Admin-Token':token.value}});if(!r.ok)throw Error('Authentication or request failed');localStorage.setItem('adminToken',token.value);return r.json()}
async function refresh(){const d=await fetch('/api/diagnostics').then(r=>r.json());document.querySelector('#faults').innerHTML=Object.entries(definitions).map(([k,v])=>`<article class="card"><span class="tag">${d.faults[k]?'ACTIVE':'READY'}</span><h2>${v[0]}</h2><p class="muted">${v[1]}</p><button onclick="toggleFault('${k}')">${d.faults[k]?'Disable':'Enable'} fault</button></article>`).join('')}
async function toggleFault(k){try{await call('/admin/faults/'+k,'POST');show('Fault updated');refresh()}catch(e){show(e.message)}}
async function resetFaults(){try{await call('/admin/faults','DELETE');show('All faults reset');refresh()}catch(e){show(e.message)}}refresh();
</script>""")


def authorize(token: str | None) -> None:
    if token != admin_token:
        raise HTTPException(status_code=401, detail="Provide the X-Admin-Token header")


@app.post("/admin/faults/{fault_name}")
async def toggle_fault(fault_name: str, x_admin_token: str | None = Header(default=None)):
    authorize(x_admin_token)
    if fault_name not in faults:
        raise HTTPException(status_code=404, detail="Unknown fault")
    faults[fault_name] = not faults[fault_name]
    return faults


@app.delete("/admin/faults")
async def reset_faults(x_admin_token: str | None = Header(default=None)):
    authorize(x_admin_token)
    for name in faults:
        faults[name] = False
    return faults


@app.get("/api/diagnostics")
async def diagnostics():
    return {"faults": faults, "productCount": len(products), "orderCount": len(orders_store)}
