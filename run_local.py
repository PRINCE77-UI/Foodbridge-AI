import os, secrets, getpass, re
import uvicorn

HERE = os.path.dirname(os.path.abspath(__file__))
ENV = os.path.join(HERE, ".env")

def load_env():
    if os.path.exists(ENV):
        for line in open(ENV, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

if __name__ == "__main__":
    os.chdir(HERE)
    load_env()
    if not (os.environ.get("FB_ADMIN_PHONE") and os.environ.get("FB_ADMIN_PASSWORD")):
        print("First time setup: choose the ADMIN login (only you will know it).")
        while True:
            phone = input("Admin mobile number (10 digits): ").strip()
            if re.fullmatch(r"[6-9]\d{9}", phone): break
            print("Enter a valid 10 digit mobile number.")
        while True:
            pw = getpass.getpass("Admin password (min 8 characters, typing is hidden): ")
            if len(pw) >= 8 and pw == getpass.getpass("Type the password again: "): break
            print("Password too short or did not match. Try again.")
        url = input("MongoDB connection link (mongodb+srv://... from Atlas, or mongodb://localhost:27017): ").strip()
        with open(ENV, "w", encoding="utf-8") as f:
            f.write(f"FB_SECRET={secrets.token_hex(32)}\nMONGODB_URL={url}\nMONGODB_DB=foodbridge\nFB_ADMIN_PHONE={phone}\nFB_ADMIN_PASSWORD={pw}\n")
        load_env()
        print("Saved in .env on this computer. Do not share or upload that file.\n")
    print("FoodBridge running at http://localhost:8000  (press Ctrl+C to stop)")
    uvicorn.run("backend.main:app", host="127.0.0.1", port=int(os.environ.get("PORT", "8000")), reload=True)
