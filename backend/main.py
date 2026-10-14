import hashlib, hmac, os, secrets, time
from urllib.parse import quote_plus, unquote
from collections import defaultdict
from pathlib import Path
import jwt
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from pymongo import MongoClient, ReturnDocument
from pymongo.errors import DuplicateKeyError, PyMongoError
from . import agents

SECRET = os.environ.get("FB_SECRET") or secrets.token_hex(32)
FRONT = Path(__file__).resolve().parent.parent / "frontend"
MIN = 60_000
app = FastAPI(title="FoodBridge AI")

if os.environ.get("FB_MOCK") == "1":
    import mongomock
    DB = mongomock.MongoClient()["foodbridge_test"]
else:
    def fix_mongo_url(url):
        url = url.strip().strip('"').strip("'")
        scheme, sep, rest = url.partition("://")
        if sep and "@" not in rest and scheme.startswith("mongodb+srv"):
            raise RuntimeError("MONGODB_URL looks wrong: there must be an @ between the password and cluster0... "
                               "Format: mongodb+srv://USERNAME:PASSWORD@cluster0.xxxx.mongodb.net/?appName=Cluster0")
        if not sep or "@" not in rest:
            return url
        userinfo, _, hostpart = rest.rpartition("@")
        user, colon, pw = userinfo.partition(":")
        pw = pw.strip()
        if pw.startswith("<") and pw.endswith(">"):
            pw = pw[1:-1]
        return f"{scheme}://{quote_plus(unquote(user))}{colon}{quote_plus(unquote(pw)) if colon else ''}@{hostpart}"

    URL = os.environ.get("MONGODB_URL")
    URL = fix_mongo_url(URL) if URL else URL
    if not URL:
        raise RuntimeError("MONGODB_URL is not set. Put your MongoDB connection link in the environment variable MONGODB_URL.")
    DB = MongoClient(URL, serverSelectionTimeoutMS=8000)[os.environ.get("MONGODB_DB", "foodbridge")]

def next_ids(con, name, count=1):
    n = con.counters.find_one_and_update({"_id": name}, {"$inc": {"n": count}}, upsert=True, return_document=ReturnDocument.AFTER)["n"]
    return list(range(n - count + 1, n + 1))

def init_db():
    try:
        DB.users.create_index("phone", unique=True)
        DB.users.create_index("id", unique=True)
        DB.listings.create_index("id", unique=True)
        DB.listings.create_index([("status", 1), ("expires_at", 1)])
        DB.notifications.create_index([("user_id", 1), ("id", -1)])
    except PyMongoError as e:
        raise RuntimeError("Cannot connect to MongoDB. Check MONGODB_URL and, in Atlas, Network Access (allow your IP). Details: " + str(e)[:200])
    phone, pw = os.environ.get("FB_ADMIN_PHONE"), os.environ.get("FB_ADMIN_PASSWORD")
    if phone and pw and len(pw) >= 8 and not DB.users.find_one({"phone": phone}):
        salt = secrets.token_hex(16)
        DB.users.insert_one({"id": next_ids(DB, "users")[0], "name": "FoodBridge Admin", "phone": phone, "salt": salt, "pw": hash_pw(pw, salt),
                             "role": "admin", "area": "", "lat": None, "lon": None, "cap": None, "veg": 0, "created_at": now(), "verified": 1, "reg_no": ""})

FAILS = defaultdict(list)

def client_key(request, phone):
    ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (request.client.host if request.client else "")
    return f"{ip}|{phone}"

def check_rate(key):
    t = time.time()
    FAILS[key] = [x for x in FAILS[key] if t - x < 600]
    if len(FAILS[key]) >= 5:
        raise HTTPException(429, "Too many wrong attempts. Try again in 10 minutes.")

@app.middleware("http")
async def security_headers(request, call_next):
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    resp.headers["Strict-Transport-Security"] = "max-age=31536000"
    resp.headers["Content-Security-Policy"] = ("default-src 'self'; script-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com; "
                                               "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdnjs.cloudflare.com; "
                                               "font-src https://fonts.gstatic.com; img-src 'self' data: https://tile.openstreetmap.org https://*.tile.openstreetmap.org https://cdnjs.cloudflare.com; "
                                               "connect-src 'self'; frame-ancestors 'none'")
    return resp

def db():
    return DB

def now():
    return int(time.time() * 1000)

def hash_pw(pw, salt):
    return hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1).hex()

def make_token(uid):
    return jwt.encode({"sub": str(uid), "exp": int(time.time()) + 30 * 86400}, SECRET, algorithm="HS256")

def current_user(authorization: str = Header(default=""), con=Depends(db)):
    try:
        uid = int(jwt.decode(authorization.removeprefix("Bearer "), SECRET, algorithms=["HS256"])["sub"])
    except Exception:
        raise HTTPException(401, "Please log in again")
    row = con.users.find_one({"id": uid}, {"_id": 0})
    if not row:
        raise HTTPException(401, "Please log in again")
    return row

def need_role(user, role):
    if user["role"] != role:
        raise HTTPException(403, f"Only a {role} can do this")

def notify(con, user_ids, text):
    user_ids = list(dict.fromkeys(user_ids))
    if user_ids:
        nid = next_ids(con, "notifications", len(user_ids))
        con.notifications.insert_many([{"id": i, "user_id": u, "text": text, "created_at": now(), "read": 0} for i, u in zip(nid, user_ids)])

def ids(con, role):
    return [r["id"] for r in con.users.find({"role": role}, {"_id": 0, "id": 1})]

def nearby(con, role, lat, lon, km=30):
    out = []
    for r in con.users.find({"role": role}, {"_id": 0, "id": 1, "lat": 1, "lon": 1, "veg": 1, "verified": 1}):
        d = agents.distance_km(lat, lon, r.get("lat"), r.get("lon"))
        if d is None or d <= km:
            out.append(r)
    return out

def expire_stale(con):
    for r in list(con.listings.find({"status": {"$in": ["open", "accepted", "picked"]}, "expires_at": {"$lt": now()}}, {"_id": 0})):
        if con.listings.update_one({"id": r["id"], "status": r["status"]}, {"$set": {"status": "expired"}}).modified_count == 1:
            notify(con, [x for x in (r["donor_id"], r.get("ngo_id"), r.get("vol_id")) if x],
                   f"Safe time for {r['item']} has ended. It was not delivered in time and should not be served.")

class Register(BaseModel):
    name: str = Field(min_length=2, max_length=60)
    phone: str = Field(pattern=r"^[6-9]\d{9}$")
    password: str = Field(min_length=6, max_length=100)
    role: str = Field(pattern=r"^(donor|ngo|volunteer)$")
    area: str = Field(default="", max_length=60)
    lat: float | None = None
    lon: float | None = None
    cap: int | None = Field(default=None, ge=1, le=100000)
    veg: bool = False
    reg_no: str = Field(default="", max_length=40)

class Login(BaseModel):
    phone: str
    password: str

class NewListing(BaseModel):
    item: str = Field(min_length=2, max_length=80)
    meals: int = Field(ge=1, le=5000)
    hours: float = Field(gt=0, le=12)
    non_veg: bool = False
    packaged: bool = False
    address: str = Field(default="", max_length=120)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)

def public_user(u):
    return {k: u[k] for k in ("id", "name", "phone", "role", "area", "lat", "lon", "cap", "veg", "verified", "reg_no")}

@app.post("/api/register")
def register(b: Register, con=Depends(db)):
    salt = secrets.token_hex(16)
    uid = next_ids(con, "users")[0]
    try:
        con.users.insert_one({"id": uid, "name": b.name.strip(), "phone": b.phone, "salt": salt, "pw": hash_pw(b.password, salt), "role": b.role,
                              "area": b.area.strip(), "lat": b.lat, "lon": b.lon, "cap": b.cap, "veg": int(b.veg), "created_at": now(),
                              "verified": 0 if b.role == "ngo" else 1, "reg_no": b.reg_no.strip()})
    except DuplicateKeyError:
        raise HTTPException(409, "This phone number is already registered")
    if b.role == "ngo":
        notify(con, ids(con, "admin"), f"New NGO waiting for verification: {b.name.strip()}")
    return {"token": make_token(uid)}

@app.post("/api/login")
def login(b: Login, request: Request, con=Depends(db)):
    key = client_key(request, b.phone)
    check_rate(key)
    u = con.users.find_one({"phone": b.phone}, {"_id": 0})
    if not u or not hmac.compare_digest(hash_pw(b.password, u["salt"]), u["pw"]):
        FAILS[key].append(time.time())
        raise HTTPException(401, "Wrong phone number or password")
    return {"token": make_token(u["id"])}

@app.get("/api/me")
def me(u=Depends(current_user)):
    return public_user(u)

class Loc(BaseModel):
    lat: float
    lon: float

@app.post("/api/me/location")
def set_location(b: Loc, u=Depends(current_user), con=Depends(db)):
    con.users.update_one({"id": u["id"]}, {"$set": {"lat": b.lat, "lon": b.lon}})
    return {"ok": True}

def attach(con, rows):
    want = {x for r in rows for x in (r["donor_id"], r.get("ngo_id"), r.get("vol_id")) if x}
    people = {r["id"]: r for r in con.users.find({"id": {"$in": list(want)}}, {"_id": 0, "id": 1, "name": 1, "phone": 1, "lat": 1, "lon": 1})}
    for r in rows:
        n = people.get(r.get("ngo_id"))
        r["ngo_lat"], r["ngo_lon"] = (n.get("lat"), n.get("lon")) if n else (None, None)
        for k in ("donor", "ngo", "vol"):
            p = people.get(r.get(k + "_id"))
            r[k + "_name"], r[k + "_phone"] = (p["name"], p["phone"]) if p else (None, None)
    return rows

def view(row, u):
    l = dict(row)
    involved = u["role"] == "admin" or u["id"] in (l["donor_id"], l.get("ngo_id"), l.get("vol_id"))
    if involved:
        l["map_lat"], l["map_lon"], l["exact"] = l.get("lat"), l.get("lon"), True
        l["route_km"] = agents.distance_km(l.get("lat"), l.get("lon"), l.get("ngo_lat"), l.get("ngo_lon"))
    else:
        l["address"] = None
        l["donor_phone"] = l["ngo_phone"] = l["vol_phone"] = None
        l["ngo_lat"] = l["ngo_lon"] = l["route_km"] = None
        r2 = lambda x: round(x, 2) if x is not None else None
        l["map_lat"], l["map_lon"], l["exact"] = r2(l.get("lat")), r2(l.get("lon")), False
    l["distance_km"] = agents.distance_km(u.get("lat"), u.get("lon"), l.get("lat"), l.get("lon"))
    l["tags"] = agents.match_tags(l, u) if u["role"] == "ngo" else []
    l.pop("lat", None); l.pop("lon", None)
    return l

@app.get("/api/listings")
def listings(u=Depends(current_user), con=Depends(db)):
    expire_stale(con)
    rows = attach(con, list(con.listings.find({}, {"_id": 0}).sort("created_at", -1).limit(300)))
    return [view(r, u) for r in rows]

@app.post("/api/listings")
def post_listing(b: NewListing, u=Depends(current_user), con=Depends(db)):
    need_role(u, "donor")
    s = agents.safety_agent(b.hours, b.packaged)
    if not s["ok"]:
        raise HTTPException(400, "Safety check failed: not enough safe time left to deliver this food")
    t, lid = now(), next_ids(con, "listings")[0]
    con.listings.insert_one({"id": lid, "donor_id": u["id"], "item": b.item.strip(), "meals": b.meals, "non_veg": int(b.non_veg), "packaged": int(b.packaged),
                             "address": b.address.strip(), "lat": b.lat if b.lat is not None else u.get("lat"), "lon": b.lon if b.lon is not None else u.get("lon"), "created_at": t, "expires_at": t + s["window_min"] * MIN,
                             "status": "open", "ngo_id": None, "vol_id": None, "accepted_at": None, "picked_at": None, "delivered_at": None})
    targets = [r["id"] for r in nearby(con, "ngo", b.lat if b.lat is not None else u.get("lat"), b.lon if b.lon is not None else u.get("lon")) if r.get("verified") == 1 and not (r.get("veg") == 1 and b.non_veg)]
    notify(con, targets, f"New food: {b.meals} meals of {b.item} from {u['name']}")
    return {"id": lid, "window_min": s["window_min"]}

def transition(con, flt, update, err):
    if con.listings.update_one(flt, {"$set": update}).matched_count != 1:
        raise HTTPException(409, err)

def get_listing(con, lid):
    expire_stale(con)
    r = con.listings.find_one({"id": lid}, {"_id": 0})
    if not r:
        raise HTTPException(404, "Listing not found")
    if r["status"] == "expired":
        raise HTTPException(409, "The safe delivery time for this food has ended")
    return r

@app.post("/api/listings/{lid}/accept")
def accept(lid: int, u=Depends(current_user), con=Depends(db)):
    need_role(u, "ngo")
    if u.get("verified") != 1:
        raise HTTPException(403, "Your NGO is not verified yet. An admin will review it soon.")
    l = get_listing(con, lid)
    if not agents.can_accept(l, u):
        raise HTTPException(400, "This food does not match your diet rule")
    transition(con, {"id": lid, "status": "open", "expires_at": {"$gt": now()}}, {"status": "accepted", "ngo_id": u["id"], "accepted_at": now()},
               "Someone else already took this, or it expired")
    notify(con, [l["donor_id"]], f"{u['name']} accepted your {l['item']}. A volunteer will be assigned.")
    notify(con, [r["id"] for r in nearby(con, "volunteer", l.get("lat"), l.get("lon"))], f"Pickup needed: {l['meals']} meals of {l['item']} for {u['name']}")
    return {"ok": True}

@app.post("/api/listings/{lid}/take")
def take(lid: int, u=Depends(current_user), con=Depends(db)):
    need_role(u, "volunteer")
    l = get_listing(con, lid)
    transition(con, {"id": lid, "status": "accepted", "vol_id": None}, {"vol_id": u["id"]}, "Another volunteer already took this pickup")
    notify(con, [l["donor_id"], l["ngo_id"]], f"{u['name']} is picking up {l['item']}")
    return {"ok": True}

@app.post("/api/listings/{lid}/release")
def release(lid: int, u=Depends(current_user), con=Depends(db)):
    need_role(u, "volunteer")
    l = get_listing(con, lid)
    transition(con, {"id": lid, "vol_id": u["id"], "status": "accepted"}, {"vol_id": None}, "You can only give back a pickup you have not collected yet")
    notify(con, [l["donor_id"], l["ngo_id"]], f"{u['name']} can no longer pick up {l['item']}. Looking for another volunteer.")
    notify(con, [r["id"] for r in nearby(con, "volunteer", l.get("lat"), l.get("lon")) if r["id"] != u["id"]], f"Pickup needed again: {l['meals']} meals of {l['item']}")
    return {"ok": True}

@app.post("/api/listings/{lid}/pick")
def pick(lid: int, u=Depends(current_user), con=Depends(db)):
    need_role(u, "volunteer")
    l = get_listing(con, lid)
    transition(con, {"id": lid, "vol_id": u["id"], "status": "accepted"}, {"status": "picked", "picked_at": now()}, "Not your pickup, or already picked up")
    notify(con, [l["ngo_id"]], f"{l['item']} is on the way to you")
    return {"ok": True}

@app.post("/api/listings/{lid}/deliver")
def deliver(lid: int, u=Depends(current_user), con=Depends(db)):
    need_role(u, "volunteer")
    l = get_listing(con, lid)
    transition(con, {"id": lid, "vol_id": u["id"], "status": "picked"}, {"status": "delivered", "delivered_at": now()}, "Not your pickup, or not picked up yet")
    notify(con, [l["donor_id"], l["ngo_id"]], f"Delivered: {l['meals']} meals of {l['item']}. Thank you!")
    return {"ok": True}

@app.post("/api/listings/{lid}/cancel")
def cancel(lid: int, u=Depends(current_user), con=Depends(db)):
    need_role(u, "donor")
    transition(con, {"id": lid, "donor_id": u["id"], "status": "open"}, {"status": "cancelled"}, "Only your own open donations can be cancelled")
    return {"ok": True}

@app.get("/api/admin/ngos")
def admin_ngos(u=Depends(current_user), con=Depends(db)):
    need_role(u, "admin")
    rows = con.users.find({"role": "ngo"}, {"_id": 0}).sort([("verified", 1), ("created_at", -1)])
    return [{k: r.get(k) for k in ("id", "name", "phone", "area", "reg_no", "cap", "veg", "verified", "created_at")} for r in rows]

@app.get("/api/admin/users")
def admin_users(u=Depends(current_user), con=Depends(db)):
    need_role(u, "admin")
    counts = defaultdict(lambda: defaultdict(int))
    for r in con.listings.find({}, {"_id": 0, "donor_id": 1, "ngo_id": 1, "vol_id": 1, "status": 1, "meals": 1}):
        counts[r["donor_id"]]["donations"] += 1
        if r["status"] == "delivered":
            counts[r["donor_id"]]["meals"] += r["meals"]
            for k in ("ngo_id", "vol_id"):
                if r.get(k):
                    counts[r[k]]["meals"] += r["meals"]
        for k in ("ngo_id", "vol_id"):
            if r.get(k):
                counts[r[k]]["donations"] += 1
    rows = con.users.find({}, {"_id": 0, "salt": 0, "pw": 0}).sort("created_at", -1)
    return [{**r, "donations": counts[r["id"]]["donations"], "meals": counts[r["id"]]["meals"]} for r in rows]

class Verify(BaseModel):
    approve: bool

@app.post("/api/admin/ngos/{uid}/verify")
def admin_verify(uid: int, b: Verify, u=Depends(current_user), con=Depends(db)):
    need_role(u, "admin")
    if con.users.update_one({"id": uid, "role": "ngo"}, {"$set": {"verified": 1 if b.approve else -1}}).matched_count != 1:
        raise HTTPException(409, "NGO not found")
    notify(con, [uid], "Your NGO is verified. You can now accept food." if b.approve else "Your NGO could not be verified. Contact support.")
    return {"ok": True}

@app.get("/api/admin/stats")
def admin_stats(u=Depends(current_user), con=Depends(db)):
    need_role(u, "admin")
    users = {r["_id"]: r["n"] for r in con.users.aggregate([{"$group": {"_id": "$role", "n": {"$sum": 1}}}])}
    lst = {r["_id"]: r["n"] for r in con.listings.aggregate([{"$group": {"_id": "$status", "n": {"$sum": 1}}}])}
    return {"users": users, "listings": lst}

@app.get("/api/public-stats")
def public_stats(con=Depends(db)):
    res = list(con.listings.aggregate([{"$match": {"status": "delivered"}}, {"$group": {"_id": None, "m": {"$sum": "$meals"}, "n": {"$sum": 1}}}]))
    m, n = (res[0]["m"], res[0]["n"]) if res else (0, 0)
    return {"meals": m, "deliveries": n, "kg": round(m * agents.KG_PER_MEAL),
            "partners": con.users.count_documents({"role": {"$in": ["donor", "ngo"]}, "verified": 1})}

@app.get("/api/impact")
def impact(u=Depends(current_user), con=Depends(db)):
    expire_stale(con)
    rows = list(con.listings.find({}, {"_id": 0, "status": 1, "meals": 1, "created_at": 1, "delivered_at": 1, "donor_id": 1, "ngo_id": 1, "vol_id": 1}))
    done = [r for r in rows if r["status"] == "delivered"]
    meals = sum(r["meals"] for r in done)
    times = [(r["delivered_at"] - r["created_at"]) / MIN for r in done]
    return {"meals": meals, "kg": round(meals * agents.KG_PER_MEAL), "deliveries": len(done),
            "avg_min": round(sum(times) / len(times)) if times else None,
            "expired_meals": sum(r["meals"] for r in rows if r["status"] == "expired"),
            "donors": len({r["donor_id"] for r in rows}), "ngos": len({r["ngo_id"] for r in rows if r.get("ngo_id")}),
            "volunteers": len({r["vol_id"] for r in rows if r.get("vol_id")})}

@app.get("/api/notifications")
def notifications(u=Depends(current_user), con=Depends(db)):
    rows = list(con.notifications.find({"user_id": u["id"]}, {"_id": 0}).sort("id", -1).limit(30))
    return {"items": rows, "unread": sum(1 for r in rows if not r["read"])}

@app.post("/api/notifications/read")
def read_all(u=Depends(current_user), con=Depends(db)):
    con.notifications.update_many({"user_id": u["id"]}, {"$set": {"read": 1}})
    return {"ok": True}

@app.get("/api/health")
def health():
    return {"ok": True}

def file_route(path, name, media):
    def handler():
        return FileResponse(FRONT / name, media_type=media)
    app.add_api_route(path, handler, include_in_schema=False)

for p, n, m in [("/", "index.html", "text/html"), ("/about", "about.html", "text/html"), ("/how-it-works", "how-it-works.html", "text/html"),
                 ("/faq", "faq.html", "text/html"), ("/site.css", "site.css", "text/css"), ("/privacy", "privacy.html", "text/html"), ("/terms", "terms.html", "text/html"),
                ("/manifest.webmanifest", "manifest.webmanifest", "application/manifest+json"),
                ("/sw.js", "sw.js", "application/javascript"), ("/icon.svg", "icon.svg", "image/svg+xml"),
                ("/icon-192.png", "icon-192.png", "image/png"), ("/icon-512.png", "icon-512.png", "image/png")]:
    file_route(p, n, m)

init_db()
