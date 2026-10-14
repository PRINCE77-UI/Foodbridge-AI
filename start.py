import os
import uvicorn

os.chdir(os.path.dirname(os.path.abspath(__file__)))
uvicorn.run("backend.main:app", host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
