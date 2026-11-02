import os

from playwright.sync_api import Page, expect


BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")


def test_health_endpoint(page: Page) -> None:
    response = page.request.get(f"{BASE_URL}/health")
    expect(response).to_be_ok()
    assert response.json()["status"] == "ok"


def test_user_can_complete_checkout(page: Page) -> None:
    page.goto(BASE_URL)
    expect(page.locator("h1")).to_contain_text("Simple buying")
    checkout = page.locator("#checkout")
    expect(checkout).to_be_visible()
    checkout.click()


def test_catalog_lists_products(page: Page) -> None:
    page.goto(f"{BASE_URL}/products")
    expect(page.locator("[data-product]")).to_have_count(3)
    expect(page.locator("h1")).to_contain_text("Designed for daily rituals")


def test_product_detail_is_reachable(page: Page) -> None:
    page.goto(f"{BASE_URL}/products/aurora-mug")
    expect(page.locator("h1")).to_have_text("Aurora ceramic mug")
    expect(page.locator("#add-to-cart")).to_be_visible()


def test_unknown_product_returns_not_found(page: Page) -> None:
    response = page.request.get(f"{BASE_URL}/products/does-not-exist")
    assert response.status == 404


def test_products_api_returns_expected_contract(page: Page) -> None:
    response = page.request.get(f"{BASE_URL}/api/products")
    expect(response).to_be_ok()
    payload = response.json()
    assert len(payload["products"]) == 3
    assert {"id", "name", "price"} <= payload["products"][0].keys()


def test_checkout_rejects_missing_customer_data(page: Page) -> None:
    response = page.request.post(f"{BASE_URL}/api/orders", data={})
    assert response.status == 422


def test_customer_can_place_order(page: Page) -> None:
    response = page.request.post(
        f"{BASE_URL}/api/orders",
        data={"name": "Demo Customer", "email": "demo@example.com"},
    )
    expect(response).to_be_ok()
    assert response.json()["order"]["status"] == "confirmed"


def test_orders_page_is_reachable(page: Page) -> None:
    page.goto(f"{BASE_URL}/orders")
    expect(page.locator("h1")).to_have_text("Your orders")
    expect(page.locator("#orders")).to_be_visible()


def test_admin_page_is_reachable(page: Page) -> None:
    page.goto(f"{BASE_URL}/admin")
    expect(page.locator("h1")).to_have_text("Failure injection lab")
    expect(page.locator("#token")).to_be_visible()


def test_admin_api_requires_token(page: Page) -> None:
    response = page.request.post(f"{BASE_URL}/admin/faults/http_500")
    assert response.status == 401
