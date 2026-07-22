"""A production-hardened ProdKit app — the target of the `prodkit doctor` CI gate.

Everything `prodkit doctor` recommends is set here, so it scores at the top of
the range. CI runs ``prodkit doctor --app examples.configured.main:app --strict``
against it, turning the production-readiness score into a build gate.

Run:  uvicorn main:app
Audit: prodkit doctor --app main:app --strict --min-score 90
"""

from fastapi import FastAPI

from prodkit import Production

app = FastAPI(title="Configured Example")

Production(
    app,
    environment="production",
    security={
        "trusted_hosts": ["api.example.com"],
        "content_security_policy": "default-src 'self'",
    },
    cors={"origins": ["https://app.example.com"]},
    rate_limit={"default": "100/minute"},
)


@app.get("/hello")
def hello() -> dict[str, str]:
    return {"message": "Hello from a hardened, production-ready app"}
