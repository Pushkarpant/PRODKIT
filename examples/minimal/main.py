"""The ProdKit one-liner.

Run:  uvicorn main:app
Try:  curl -i localhost:8000/hello
      curl -i localhost:8000/health
      curl -i localhost:8000/ready
"""

from fastapi import FastAPI

from prodkit import Production

app = FastAPI()
Production(app, environment="development")


@app.get("/hello")
def hello() -> dict[str, str]:
    return {"message": "Hello from a production-ready app"}
