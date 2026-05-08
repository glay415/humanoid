"""python -m ui.backend  →  http://localhost:8000

Vite 프론트엔드(localhost:5173)와 함께 띄울 때 이 진입점 사용.
"""
import uvicorn

from ui.backend.app import app


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
