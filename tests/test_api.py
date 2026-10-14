import os, sys, tempfile
os.environ["FB_MOCK"] = "1"
os.environ["FB_SECRET"] = "test"
os.environ["FB_ADMIN_PHONE"] = "9999900000"
os.environ["FB_ADMIN_PASSWORD"] = "test-admin-pass"
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from fastapi.testclient import TestClient
from backend.main import app
c = TestClient(app)

def hdr(token):
    return {"Authorization": "Bearer " + token}

def user(name, phone, role, **kw):
    r = c.post("/api/register", json={"name": name, "phone": phone, "password": "secret1", "role": role, **kw})
    assert r.status_code == 200, r.text
    return hdr(r.json()["token"])

admin = hdr(c.post("/api/login", json={"phone": "9999900000", "password": "test-admin-pass"}).json()["token"])

def verify(h, approve=True):
    uid = c.get("/api/me", headers=h).json()["id"]
    assert c.post(f"/api/admin/ngos/{uid}/verify", headers=admin, json={"approve": approve}).status_code == 200

donor = user("Hotel Saffron", "9000000001", "donor", lat=23.03, lon=72.56)
ngo = user("Asha Shelter", "9000000002", "ngo", lat=23.04, lon=72.57, cap=100, reg_no="GJ/2020/123")
vegngo = user("Seva Kitchen", "9000000003", "ngo", veg=True)
newngo = user("New NGO", "9000000006", "ngo")
vol = user("Ravi", "9000000004", "volunteer")
vol2 = user("Meena", "9000000005", "volunteer")
verify(ngo); verify(vegngo)

def post(h=donor, **kw):
    return c.post("/api/listings", headers=h, json={"item": "Veg biryani", "meals": 50, "hours": 3, "address": "MG Road 12", **kw})

def test_register_login_and_duplicate():
    assert c.post("/api/register", json={"name": "X Y", "phone": "9000000001", "password": "secret1", "role": "donor"}).status_code == 409
    assert c.post("/api/login", json={"phone": "9000000001", "password": "secret1"}).status_code == 200
    assert c.get("/api/me").status_code == 401

def test_login_rate_limit():
    for _ in range(5):
        assert c.post("/api/login", json={"phone": "9000000005", "password": "bad"}).status_code == 401
    assert c.post("/api/login", json={"phone": "9000000005", "password": "secret1"}).status_code == 429

def test_full_flow_and_impact():
    lid = post().json()["id"]
    assert c.post(f"/api/listings/{lid}/accept", headers=ngo).status_code == 200
    assert c.post(f"/api/listings/{lid}/accept", headers=vegngo).status_code == 409
    assert c.post(f"/api/listings/{lid}/take", headers=vol).status_code == 200
    assert c.post(f"/api/listings/{lid}/take", headers=vol2).status_code == 409
    assert c.post(f"/api/listings/{lid}/deliver", headers=vol).status_code == 409
    assert c.post(f"/api/listings/{lid}/pick", headers=vol).status_code == 200
    assert c.post(f"/api/listings/{lid}/deliver", headers=vol).status_code == 200
    m = c.get("/api/impact", headers=donor).json()
    assert m["meals"] >= 50 and m["deliveries"] >= 1
    assert c.get("/api/public-stats").json()["meals"] >= 50

def test_unverified_ngo_cannot_accept_until_approved():
    lid = post().json()["id"]
    assert c.post(f"/api/listings/{lid}/accept", headers=newngo).status_code == 403
    verify(newngo)
    assert c.post(f"/api/listings/{lid}/accept", headers=newngo).status_code == 200

def test_admin_only_and_stats():
    assert c.get("/api/admin/ngos", headers=donor).status_code == 403
    assert any(n["reg_no"] == "GJ/2020/123" for n in c.get("/api/admin/ngos", headers=admin).json())
    assert c.get("/api/admin/stats", headers=admin).json()["users"]["ngo"] >= 3

def test_cancel_only_own_open():
    lid = post().json()["id"]
    assert c.post(f"/api/listings/{lid}/cancel", headers=ngo).status_code == 403
    assert c.post(f"/api/listings/{lid}/cancel", headers=donor).status_code == 200
    assert c.post(f"/api/listings/{lid}/accept", headers=ngo).status_code == 409

def test_safety_rejects_and_roles():
    assert post(hours=0.2).status_code == 400
    assert c.post("/api/listings", headers=ngo, json={"item": "x y", "meals": 5, "hours": 3}).status_code == 403

def test_diet_rule_and_address_privacy():
    lid = post(non_veg=True, item="Chicken curry").json()["id"]
    assert c.post(f"/api/listings/{lid}/accept", headers=vegngo).status_code == 400
    seen = [l for l in c.get("/api/listings", headers=vol).json() if l["id"] == lid][0]
    assert seen["address"] is None
    own = [l for l in c.get("/api/listings", headers=donor).json() if l["id"] == lid][0]
    assert own["address"] == "MG Road 12"
    near = [l for l in c.get("/api/listings", headers=ngo).json() if l["id"] == lid][0]
    assert near["distance_km"] is not None and "Fits your diet rule" in near["tags"]

def test_static_pages_and_headers():
    for path, ct in [("/", "text/html"), ("/privacy", "text/html"), ("/terms", "text/html"), ("/manifest.webmanifest", "manifest"), ("/sw.js", "javascript"), ("/icon-192.png", "png")]:
        r = c.get(path)
        assert r.status_code == 200 and ct in r.headers["content-type"], path
    assert c.get("/").headers["x-frame-options"] == "DENY"

def _row(h, lid):
    return [x for x in c.get("/api/listings", headers=h).json() if x["id"] == lid][0]

def test_phones_and_release():
    lid = post().json()["id"]
    assert c.post(f"/api/listings/{lid}/accept", headers=ngo).status_code == 200
    assert c.post(f"/api/listings/{lid}/take", headers=vol).status_code == 200
    assert _row(vol, lid)["donor_phone"] == "9000000001"
    assert _row(donor, lid)["vol_phone"] == "9000000004"
    assert c.post(f"/api/listings/{lid}/release", headers=vol).status_code == 200
    assert c.post(f"/api/listings/{lid}/release", headers=vol).status_code == 409
    assert c.post(f"/api/listings/{lid}/take", headers=vol2).status_code == 200

def test_expired_listing_is_closed():
    from backend import main
    lid = post().json()["id"]
    main.DB.listings.update_one({"id": lid}, {"$set": {"expires_at": 1}})
    assert c.post(f"/api/listings/{lid}/accept", headers=ngo).status_code == 409
    assert _row(donor, lid)["status"] == "expired"

def test_admin_sees_everything_and_map_is_private():
    lid = post(lat=23.0312, lon=72.5611).json()["id"]
    outsider = _row(vol2, lid)
    assert outsider["address"] is None and outsider["donor_phone"] is None
    assert outsider["exact"] is False and outsider["map_lat"] == 23.03
    mine = _row(donor, lid)
    assert mine["exact"] is True and mine["map_lat"] == 23.0312 and mine["address"] == "MG Road 12"
    seen = _row(admin, lid)
    assert seen["address"] == "MG Road 12" and seen["donor_phone"] == "9000000001" and seen["exact"] is True
    users = c.get("/api/admin/users", headers=admin).json()
    assert any(u["phone"] == "9000000001" for u in users)
    assert all("pw" not in u and "salt" not in u for u in users)
    assert c.get("/api/admin/users", headers=donor).status_code == 403

def test_pickup_to_ngo_distance_and_pages():
    lid = post(lat=23.03, lon=72.56).json()["id"]
    c.post("/api/me/location", headers=ngo, json={"lat": 23.05, "lon": 72.58})
    assert c.post(f"/api/listings/{lid}/accept", headers=ngo).status_code == 200
    assert _row(donor, lid)["route_km"] is not None
    for path in ("/about", "/how-it-works", "/faq", "/site.css"):
        assert c.get(path).status_code == 200
