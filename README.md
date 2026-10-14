# FoodBridge AI

Surplus food from hotels and caterers goes to verified NGOs, delivered by volunteers, inside a safe-time countdown.

Stack: FastAPI, MongoDB (Atlas), a single-page frontend (installable PWA), Docker, Render.

## Features
- Donors post food with a pickup pin on the map. A Safety Agent sets the delivery deadline, and expired food is closed automatically.
- NGOs must be verified by the admin before they can accept food. Two NGOs can never take the same donation.
- Volunteers take pickups and get directions to the donor and to the NGO.
- Alerts reach only verified NGOs and volunteers within 30 km.
- Phone numbers and exact addresses are visible only to the people in a pickup and to the admin. Everyone else sees an approximate map area.
- Admin area: verify NGOs, see every person and donation (search, filters, CSV), map of everything.
- Public pages: home, how it works, FAQ, about, privacy, terms.

## Setup
1. **MongoDB Atlas:** create a free cluster, add a database user, allow network access, then copy the connection link
   (`mongodb+srv://USER:PASSWORD@cluster.../`). Special characters in the password are escaped automatically.
2. **Run locally:**
   ```
   pip install -r requirements-dev.txt
   python run_local.py
   ```
   Open http://localhost:8000. On first run it asks for the MongoDB link and your admin phone and password, and saves them in `.env` (git-ignored).
3. **Tests:** `pytest` (uses an in-memory fake database).

## Deploy on Render
1. Push this folder to GitHub. Check that `.env` is not included.
2. Render: New, Blueprint, choose the repository.
3. In Render, Environment, set `MONGODB_URL`, `FB_ADMIN_PHONE` and `FB_ADMIN_PASSWORD`. `FB_SECRET` is generated for you.
4. In Atlas, Network Access, allow `0.0.0.0/0` so Render can connect.

## Configuration
| Variable | Purpose |
|---|---|
| `MONGODB_URL` | MongoDB connection link (required) |
| `MONGODB_DB` | Database name (default `foodbridge`) |
| `FB_SECRET` | Key used to sign login tokens. Keep it fixed in production |
| `FB_ADMIN_PHONE`, `FB_ADMIN_PASSWORD` | Admin login, created on first start (password at least 8 characters) |

## Notes
- Maps use Leaflet from cdnjs and OpenStreetMap tiles, so they need internet. For heavy traffic use a tile provider.
- Not built yet: SMS OTP verification, password reset. Set a real contact email in `frontend/privacy.html` and the home page footer.
