# HAND-WRITTEN v0 STUB, not agent-generated. It exists to baseline the gate and is
# replaced by the first generated port.
from fastapi import FastAPI

app = FastAPI()


@app.get("/healthz")
def healthz():
    return {"ok": True, "version": "3.11.2"}
