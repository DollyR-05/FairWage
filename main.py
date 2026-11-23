"""FairWage backend: FastAPI + database.py.
Run:  pip install -r requirements.txt
      uvicorn main:app --reload      then open http://localhost:8000
For phones on the same Wi-Fi: uvicorn main:app --host 0.0.0.0 --port 8000
"""
import hmac, os, secrets, time
from fastapi import FastAPI, Header, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import database as db

OTPS = {}  # phone -> {"otp", "exp", "tries"}. Demo: the OTP is shown on screen instead of sent by SMS.
PHONE = r"^[6-9][0-9]{9}$"

class PhoneIn(BaseModel):
    phone: str = Field(pattern=PHONE)

class VerifyIn(PhoneIn):
    otp: str = Field(pattern=r"^[0-9]{6}$")

class RegisterIn(VerifyIn):
    name: str = Field(min_length=2, max_length=40)
    role: str = Field(pattern=r"^(worker|parttimer|employer)$")

class JobIn(BaseModel):
    title: str = Field(pattern=r"^(Mason|Painter|Cleaner|Helper|Loader|Gardener)$")
    unit: str = Field(pattern=r"^(hour|day)$")
    rate: int = Field(ge=1, le=100000)
    units: int = Field(ge=1, le=365)
    need: int = Field(ge=1, le=100)
    lat: float
    lng: float

class MoveIn(BaseModel):
    amount: int = Field(ge=1)

class CashIn(BaseModel):
    method: str = Field(pattern=r"^(agent|bank)$")

class WorkerIn(BaseModel):
    worker: str = Field(pattern=PHONE)

app = FastAPI(title="FairWage API")

def who(x_token: str = Header(default=None)):
    phone = db.phone_for_token(x_token) if x_token else None
    if not phone:
        raise HTTPException(401, "Please log in again")
    return phone

def run(fn, *args):
    try:
        return fn(*args)
    except ValueError as e:
        raise HTTPException(409 if "already" in str(e) else 400, str(e))

def check_otp(phone, otp):
    s = OTPS.get(phone)
    if not s or s["exp"] < time.time():
        raise HTTPException(400, "That OTP is wrong or has expired")
    if s["tries"] >= 5:
        OTPS.pop(phone, None)
        raise HTTPException(400, "Too many wrong attempts. Please ask for a new OTP")
    if not hmac.compare_digest(s["otp"], otp):
        s["tries"] += 1
        raise HTTPException(400, "That OTP is wrong or has expired")

def public(user):
    return {k: user[k] for k in ("phone", "name", "role")}

@app.post("/api/otp")
def send_otp(body: PhoneIn):
    otp = str(secrets.randbelow(900000) + 100000)
    OTPS[body.phone] = {"otp": otp, "exp": time.time() + 300, "tries": 0}
    # Demo: the OTP is returned so it can be shown on screen. In production, send it by SMS instead.
    return {"exists": db.get_user(body.phone) is not None, "otp": otp}

@app.post("/api/verify")
def verify(body: VerifyIn):
    check_otp(body.phone, body.otp)
    user = db.get_user(body.phone)
    if not user:
        return {"user": None, "token": None}
    OTPS.pop(body.phone, None)
    return {"user": public(user), "token": db.create_session(body.phone)}

@app.post("/api/register")
def register(body: RegisterIn):
    check_otp(body.phone, body.otp)
    user = run(db.add_user, body.phone, body.name, body.role)
    OTPS.pop(body.phone, None)
    return {"user": public(user), "token": db.create_session(body.phone)}

@app.get("/api/state")
def state(x_token: str = Header(default=None)):
    return db.get_state(who(x_token))

@app.post("/api/jobs")
def post_job(body: JobIn, x_token: str = Header(default=None)):
    return {"id": run(db.post_job, who(x_token), body.title, body.unit, body.rate, body.units, body.need, body.lat, body.lng)}

@app.post("/api/jobs/{job_id}/accept")
def accept(job_id: str, x_token: str = Header(default=None)):
    run(db.accept_job, job_id, who(x_token))
    return {"ok": True}

@app.post("/api/jobs/{job_id}/mark")
def mark(job_id: str, x_token: str = Header(default=None)):
    run(db.mark_done, job_id, who(x_token))
    return {"ok": True}

@app.post("/api/jobs/{job_id}/confirm")
def confirm(job_id: str, body: WorkerIn, x_token: str = Header(default=None)):
    run(db.confirm_work, job_id, who(x_token), body.worker)
    return {"ok": True}

@app.post("/api/jobs/{job_id}/sim")
def sim(job_id: str, x_token: str = Header(default=None)):
    run(db.confirm_work, job_id, None, who(x_token), True)
    return {"ok": True}

@app.post("/api/wallet/move")
def move(body: MoveIn, x_token: str = Header(default=None)):
    run(db.move_to_c, who(x_token), body.amount)
    return {"ok": True}

@app.post("/api/wallet/cash")
def cash(body: CashIn, x_token: str = Header(default=None)):
    return run(db.cash_out, who(x_token), body.method)

@app.post("/api/ledger/verify")
def ledger_verify(x_token: str = Header(default=None)):
    who(x_token)
    return db.verify_chain()

@app.post("/api/ledger/tamper")
def ledger_tamper(x_token: str = Header(default=None)):
    who(x_token)
    return run(db.tamper_demo)

@app.post("/api/ledger/restore")
def ledger_restore(x_token: str = Header(default=None)):
    who(x_token)
    db.restore_demo()
    return {"ok": True}

app.mount("/", StaticFiles(directory=os.path.join(os.path.dirname(os.path.abspath(__file__)), "static"), html=True), name="static")