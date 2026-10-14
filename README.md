# FoodBridge AI

**Surplus food, delivered before it spoils.**

FoodBridge AI is a web platform where hotels, caterers and canteens post their leftover food, verified NGOs accept it, and volunteers deliver it, all inside a safe-time countdown that everyone can see. Built for **SDG 2: Zero Hunger** (and target 12.3 on reducing food waste).

Live demo: [Link ](https://foodbridge-axwt.onrender.com)here. 

---

## Why this project

Every day, good food from hotels, caterers and event halls is thrown away, while NGOs and shelters struggle to arrange fresh meals. The UNEP Food Waste Index Report 2024 estimates that about 1.05 billion tonnes of food were wasted worldwide in 2022, and Indian households alone wasted about 78 million tonnes.

The gap is not only supply. It is **time and trust**: cooked food stays safe for only a few hours, donors do not know which NGO to call, and coordination by phone or chat groups is slow and leaves no record. FoodBridge AI turns that phone call into a tracked, time-limited and verified journey.

## Features

- **Safe-time countdown.** Every donation gets a delivery deadline. Expired food closes automatically and cannot be accepted, collected or delivered.
- **Verified NGOs only.** An admin reviews each NGO's registration number before it can accept food.
- **Smart alerts.** Alerts go only to verified NGOs and volunteers within 30 km. Diet rules and capacity are respected.
- **Race-safe acceptance.** Two NGOs can never take the same donation (atomic database update).
- **Live map.** Donors drop a pickup pin. Volunteers get pins, the NGO drop-off point and Google Maps directions.
- **Privacy by default.** Other users see only an approximate area (about 1 km). The exact address and phone numbers are visible only to the people in that pickup and to the admin.
- **Volunteer flexibility.** A volunteer who cannot go can give a pickup back, and nearby volunteers are alerted again.
- **Admin console.** Every user and donation with search, filters, CSV export and a map.
- **Impact numbers.** Meals rescued, kilograms saved, average delivery time and expired meals.
- **Installable web app (PWA).** Works on any phone without an app store.

## How it works

1. **Donor posts** the food, number of meals, veg or non-veg, cooked or packaged, safe hours and a pickup pin.
2. **Safety check** sets the deadline. If there is not enough safe time left, the post is rejected.
3. **NGO accepts.** The first verified NGO to accept gets the food.
4. **Volunteer collects** and delivers, marking each step (picked up, delivered).
5. **Everyone is notified**, and the impact numbers are updated. If the timer reaches zero first, the donation is closed and all parties are alerted.

### The five agents

| Agent | Job |
|---|---|
| Donor Agent | Turns a post into a clear, validated listing with a pickup pin |
| Safety Agent | Sets the safe delivery deadline and closes expired food |
| Matching Agent | Finds verified NGOs within 30 km that fit diet rule and capacity |
| Logistics Agent | Alerts volunteers and tracks accepted, picked up and delivered |
| Impact Agent | Counts meals rescued, kilograms saved (0.4 kg per meal estimate) and delivery time |

The agents use clear rules today. The design allows LLM-based reasoning to be added later.

**Safety rules:** cooked food is limited to 4 hours, packaged food to the hours the donor sets (up to 12), and 20 minutes are always kept aside for handling.

## Tech stack

| Layer | Technology |
|---|---|
| Backend | Python, FastAPI |
| Database | MongoDB (Atlas) |
| Frontend | JavaScript single-page app, installable PWA |
| Maps | Leaflet with OpenStreetMap tiles |
| Auth | Salted scrypt password hashes, signed JWT login tokens |
| Testing | pytest with an in-memory fake database (mongomock) |
| Deployment | Docker, Render, GitHub Actions for tests |

## Project structure

```
.
├── backend/
│   ├── main.py            # API, database access, roles, alerts
│   └── agents.py          # Safety, matching and distance rules
├── frontend/
│   ├── index.html         # Single-page app (all roles)
│   ├── about.html, faq.html, how-it-works.html, privacy.html, terms.html
│   ├── site.css, sw.js, manifest.webmanifest, icons
├── tests/test_api.py
├── run_local.py           # Local runner with first-time setup
├── start.py               # Production start
├── Dockerfile
├── render.yaml            # Render Blueprint
├── requirements.txt
└── requirements-dev.txt
```

## Getting started

### Prerequisites

- Python 3.10 or newer
- A free [MongoDB Atlas](https://www.mongodb.com/atlas) cluster

### 1. Set up MongoDB Atlas

1. Create a free cluster.
2. Under **Database Access**, add a database user with a strong password.
3. Under **Network Access**, allow your IP address (use `0.0.0.0/0` when deploying to Render).
4. Click **Connect**, choose **Drivers**, and copy the connection link (`mongodb+srv://USER:PASSWORD@cluster.../`). Special characters in the password are escaped automatically.

### 2. Run locally

```bash
git clone https://github.com/<your-username>/foodbridge-ai.git
cd foodbridge-ai
pip install -r requirements-dev.txt
python run_local.py
```

Open http://localhost:8000. On the first run, the script asks for your MongoDB link and your admin phone number and password, and saves them in a local `.env` file (this file is git-ignored and must never be committed).

### 3. Run the tests

```bash
pytest
```

Tests use an in-memory fake database, so no real MongoDB is needed.

## Configuration

| Variable | Required | Description |
|---|---|---|
| `MONGODB_URL` | Yes | MongoDB connection link |
| `MONGODB_DB` | No | Database name (default `foodbridge`) |
| `FB_SECRET` | Recommended | Key used to sign login tokens. Keep it fixed in production, otherwise users are logged out on every restart |
| `FB_ADMIN_PHONE` | Yes | Admin phone number, created on first start |
| `FB_ADMIN_PASSWORD` | Yes | Admin password (at least 8 characters) |
| `PORT` | No | Server port (default `8000`) |

## Deployment on Render

1. Push this repository to GitHub. Make sure `.env` is not included.
2. In Render, choose **New** then **Blueprint** and select the repository (it reads `render.yaml`).
3. In the Render dashboard, set `MONGODB_URL`, `FB_ADMIN_PHONE` and `FB_ADMIN_PASSWORD`. `FB_SECRET` is generated automatically.
4. In Atlas **Network Access**, allow `0.0.0.0/0` so Render can connect.
5. After the build, open the Render link and check `/api/health`.

On Render's free plan the service sleeps after a period of inactivity, so the first request can take 30 to 50 seconds. Data lives in MongoDB, so it is not lost.

## API overview

| Method | Endpoint | Who |
|---|---|---|
| POST | `/api/register`, `/api/login` | Everyone |
| GET | `/api/me`, `/api/impact`, `/api/notifications` | Logged in |
| GET / POST | `/api/listings` | Logged in / Donor |
| POST | `/api/listings/{id}/accept` | Verified NGO |
| POST | `/api/listings/{id}/take`, `/release`, `/pick`, `/deliver` | Volunteer |
| POST | `/api/listings/{id}/cancel` | Donor |
| GET / POST | `/api/admin/ngos`, `/api/admin/users`, `/api/admin/stats`, `/api/admin/ngos/{id}/verify` | Admin |
| GET | `/api/public-stats`, `/api/health` | Everyone |

## Security and privacy

- Passwords are stored only as salted scrypt hashes.
- Signed login tokens, and every role rule is checked on the server.
- Login rate limiting and security headers (including a content security policy).
- Exact address and phone numbers are shared only with the people in a pickup and the admin.
- The admin can see all data to verify NGOs, keep the service safe and give support. This is stated in the privacy policy.

## Roadmap

- [x] Donor, NGO, volunteer and admin roles
- [x] Safety timer with automatic expiry
- [x] Map, directions and alerts
- [x] Admin data console with CSV export
- [ ] SMS OTP login and password reset
- [ ] WhatsApp alerts
- [ ] NGO document upload for verification
- [ ] Hindi and Gujarati
- [ ] LLM-powered agents and demand forecasts for NGOs
- [ ] CSR impact reports and multi-city network

## Known limitations

- Phone numbers are not verified yet (no OTP), and there is no password reset.
- The agents are rule-based, not machine-learning models.
- Maps use free OpenStreetMap tiles. For heavy traffic, switch to a tile provider.
- FoodBridge enforces time limits, but donors remain responsible for the quality of the food they give.

## Acknowledgements

- Food waste figures: [UNEP Food Waste Index Report 2024](https://www.unep.org/resources/publication/food-waste-index-report-2024)
- Maps: [Leaflet](https://leafletjs.com/) and [OpenStreetMap](https://www.openstreetmap.org/copyright) contributors
- Built as part of the IBM SkillsBuild for Academia project program.
