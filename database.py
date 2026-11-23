"""FairWage database (SQLite, Python standard library only).

Stores accounts, jobs, who accepted each job, daily verification, wallets (Block B and C),
transaction history and the hash-chained ledger. The server code in main.py calls these functions.

Command line:
    python database.py add 9876543210 "Asha" worker     # roles: worker, parttimer, employer
    python database.py list
    python database.py find 9876543210
"""
import hashlib, json, math, os, random, re, secrets, sqlite3, sys, time
from contextlib import contextmanager

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("WORKLINK_DB", os.path.join(HERE, "worklink.db"))
ROLES = ("worker", "parttimer", "employer")
PHONE_RE = re.compile(r"^[6-9][0-9]{9}$")
SEED_JOBS = [("Mason", "Sharma Constructions", 600, "day", 3, 2, 1.2), ("Painter", "Gupta Paints", 500, "day", 2, 1, 3.5),
             ("Cleaner", "Shree Office", 55, "hour", 3, 2, 0.8), ("Helper", "Verma Traders", 400, "day", 5, 3, 6.5),
             ("Loader", "Kisan Mandi", 60, "hour", 2, 4, 2.4), ("Gardener", "Green Lawns", 380, "day", 1, 1, 9.0)]

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    phone TEXT PRIMARY KEY
        CHECK (length(phone) = 10 AND phone NOT GLOB '*[^0-9]*' AND substr(phone, 1, 1) IN ('6','7','8','9')),
    name TEXT NOT NULL CHECK (length(name) BETWEEN 2 AND 40),
    role TEXT NOT NULL CHECK (role IN ('worker', 'parttimer', 'employer')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, phone TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY, seed INTEGER NOT NULL DEFAULT 0, title TEXT NOT NULL, emp TEXT NOT NULL, ename TEXT NOT NULL,
    rate INTEGER NOT NULL CHECK (rate > 0), unit TEXT NOT NULL CHECK (unit IN ('hour', 'day')),
    units INTEGER NOT NULL CHECK (units > 0), need INTEGER NOT NULL CHECK (need > 0),
    lat REAL, lng REAL, dy REAL, dx REAL);
CREATE TABLE IF NOT EXISTS acceptances (
    job_id TEXT NOT NULL, worker TEXT NOT NULL, w INTEGER NOT NULL DEFAULT 0, e INTEGER NOT NULL DEFAULT 0,
    paid INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (job_id, worker));
CREATE TABLE IF NOT EXISTS wallets (phone TEXT PRIMARY KEY, b INTEGER NOT NULL DEFAULT 0 CHECK (b >= 0), c INTEGER NOT NULL DEFAULT 0 CHECK (c >= 0));
CREATE TABLE IF NOT EXISTS tx (id INTEGER PRIMARY KEY AUTOINCREMENT, phone TEXT NOT NULL, d TEXT NOT NULL, a INTEGER NOT NULL, k TEXT NOT NULL, t INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS chain (idx INTEGER PRIMARY KEY, time INTEGER NOT NULL, data TEXT NOT NULL, prev TEXT NOT NULL, hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""

def connect():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn

@contextmanager
def _tx():
    c = connect()
    c.isolation_level = None
    c.execute("BEGIN IMMEDIATE")
    try:
        yield c
        c.execute("COMMIT")
    except Exception:
        c.execute("ROLLBACK")
        raise
    finally:
        c.close()

def _ms(): return int(time.time() * 1000)
def _canon(d): return json.dumps(d, separators=(",", ":"), sort_keys=True)
def _hash(idx, t, data, prev): return hashlib.sha256(f"{idx}|{t}|{data}|{prev}".encode()).hexdigest()
def _mk(p): return "xxxxxx" + p[-4:] if len(p) > 4 else p

def _add_block(c, data):
    last = c.execute("SELECT idx, hash FROM chain ORDER BY idx DESC LIMIT 1").fetchone()
    idx = last["idx"] + 1 if last else 0
    prev = last["hash"] if last else "0"
    t, ds = _ms(), _canon(data)
    c.execute("INSERT INTO chain (idx, time, data, prev, hash) VALUES (?, ?, ?, ?, ?)", (idx, t, ds, prev, _hash(idx, t, ds, prev)))

def init_db():
    with connect() as c:
        c.executescript(SCHEMA)
    with _tx() as c:
        if not c.execute("SELECT 1 FROM chain").fetchone():
            _add_block(c, {"type": "GENESIS", "note": "FairWage ledger started"})
        if not c.execute("SELECT 1 FROM jobs").fetchone():
            for i, (title, ename, rate, unit, units, need, km) in enumerate(SEED_JOBS):
                c.execute("INSERT INTO jobs (id, seed, title, emp, ename, rate, unit, units, need, dy, dx) VALUES (?, 1, ?, 'seed', ?, ?, ?, ?, ?, ?, ?)",
                          ("s%d" % i, title, ename, rate, unit, units, need, math.cos(i * 1.1) * km, math.sin(i * 1.1) * km))

# ---------- accounts and sessions ----------
def add_user(phone, name, role):
    name = (name or "").strip()
    if not PHONE_RE.match(phone or ""):
        raise ValueError("Enter a valid 10-digit mobile number that starts with 6, 7, 8 or 9")
    if not 2 <= len(name) <= 40:
        raise ValueError("Name must be 2 to 40 characters")
    if role not in ROLES:
        raise ValueError("Role must be worker, parttimer or employer")
    try:
        with connect() as c:
            c.execute("INSERT INTO users (phone, name, role) VALUES (?, ?, ?)", (phone, name, role))
    except sqlite3.IntegrityError:
        raise ValueError("This number is already registered")
    return get_user(phone)

def get_user(phone):
    with connect() as c:
        row = c.execute("SELECT phone, name, role, created_at FROM users WHERE phone = ?", (phone,)).fetchone()
    return dict(row) if row else None

def list_users():
    with connect() as c:
        return [dict(r) for r in c.execute("SELECT phone, name, role, created_at FROM users ORDER BY created_at")]

def create_session(phone):
    token = secrets.token_hex(16)
    with connect() as c:
        c.execute("INSERT INTO sessions (token, phone) VALUES (?, ?)", (token, phone))
    return token

def phone_for_token(token):
    with connect() as c:
        row = c.execute("SELECT phone FROM sessions WHERE token = ?", (token,)).fetchone()
    return row["phone"] if row else None

# ---------- jobs, verification and money ----------
def _wallet(c, p):
    c.execute("INSERT OR IGNORE INTO wallets (phone) VALUES (?)", (p,))
    return c.execute("SELECT b, c FROM wallets WHERE phone = ?", (p,)).fetchone()

def _log(c, p, d, a, k):
    c.execute("INSERT INTO tx (phone, d, a, k, t) VALUES (?, ?, ?, ?, ?)", (p, d, a, k, _ms()))

def _job(c, job_id):
    j = c.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if not j:
        raise ValueError("Job not found")
    return j

def _acc(c, job_id, worker):
    a = c.execute("SELECT w, e, paid FROM acceptances WHERE job_id = ? AND worker = ?", (job_id, worker)).fetchone()
    if not a:
        raise ValueError("This worker has not accepted the job")
    return a

def _settle(c, job, worker):
    a = _acc(c, job["id"], worker)
    n = min(a["w"], a["e"]) - a["paid"]
    if n > 0:
        amt = n * job["rate"]
        c.execute("UPDATE acceptances SET paid = paid + ? WHERE job_id = ? AND worker = ?", (n, job["id"], worker))
        _wallet(c, worker)
        c.execute("UPDATE wallets SET b = b + ? WHERE phone = ?", (amt, worker))
        _log(c, worker, "%s, %d %s%s verified by both" % (job["title"], n, job["unit"], "s" if n > 1 else ""), amt, "e")
        _add_block(c, {"type": "VERIFIED", "job": job["id"], "title": job["title"], "worker": _mk(worker), "unit": job["unit"], "units": n, "amount": amt})

def post_job(emp, title, unit, rate, units, need, lat, lng):
    user = get_user(emp)
    if not user:
        raise ValueError("Account not found")
    jid = "j%d" % _ms()
    with _tx() as c:
        c.execute("INSERT INTO jobs (id, seed, title, emp, ename, rate, unit, units, need, lat, lng) VALUES (?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                  (jid, title, emp, user["name"], rate, unit, units, need, lat, lng))
        _add_block(c, {"type": "POSTED", "job": jid, "title": title, "employer": _mk(emp), "total": rate * units * need})
    return jid

def accept_job(job_id, worker):
    with _tx() as c:
        j = _job(c, job_id)
        if j["emp"] == worker:
            raise ValueError("You posted this job. Use another phone number to accept it.")
        if c.execute("SELECT 1 FROM acceptances WHERE job_id = ? AND worker = ?", (job_id, worker)).fetchone():
            raise ValueError("You already accepted this job")
        if c.execute("SELECT COUNT(*) FROM acceptances WHERE job_id = ?", (job_id,)).fetchone()[0] >= j["need"]:
            raise ValueError("This job is already full")
        c.execute("INSERT INTO acceptances (job_id, worker) VALUES (?, ?)", (job_id, worker))
        _add_block(c, {"type": "ACCEPTED", "job": job_id, "title": j["title"], "worker": _mk(worker), "rate": j["rate"], "unit": j["unit"]})

def mark_done(job_id, worker):
    with _tx() as c:
        j, a = _job(c, job_id), None
        a = _acc(c, job_id, worker)
        if a["w"] >= j["units"]:
            raise ValueError("All the work is already marked done")
        c.execute("UPDATE acceptances SET w = w + 1 WHERE job_id = ? AND worker = ?", (job_id, worker))
        _settle(c, j, worker)

def confirm_work(job_id, employer, worker, demo=False):
    with _tx() as c:
        j = _job(c, job_id)
        if demo:
            if not j["seed"]:
                raise ValueError("Demo confirmation works only on demo jobs")
        elif j["emp"] != employer:
            raise ValueError("Only the employer who posted this job can confirm work")
        a = _acc(c, job_id, worker)
        if a["e"] >= a["w"]:
            raise ValueError("The worker has not marked more work done yet")
        c.execute("UPDATE acceptances SET e = e + 1 WHERE job_id = ? AND worker = ?", (job_id, worker))
        _settle(c, j, worker)

def move_to_c(phone, amount):
    with _tx() as c:
        w = _wallet(c, phone)
        if not 0 < amount <= w["b"]:
            raise ValueError("Enter an amount up to your Block B balance")
        c.execute("UPDATE wallets SET b = b - ?, c = c + ? WHERE phone = ?", (amount, amount, phone))
        _log(c, phone, "Moved from Block B to Block C", amount, "m")
        _add_block(c, {"type": "B_TO_C", "worker": _mk(phone), "amount": amount})

def cash_out(phone, method):
    with _tx() as c:
        w = _wallet(c, phone)
        if w["c"] <= 0:
            raise ValueError("Block C is empty. Move money from Block B first.")
        amt, code = w["c"], random.randint(100000, 999999)
        c.execute("UPDATE wallets SET c = 0 WHERE phone = ?", (phone,))
        _log(c, phone, "Cash via local agent, code %d" % code if method == "agent" else "Sent to UPI or bank", amt, "o")
        _add_block(c, {"type": "CASH_OUT", "worker": _mk(phone), "amount": amt, "method": "local agent" if method == "agent" else "UPI or bank"})
    return {"amount": amt, "code": code}

def get_state(phone):
    with connect() as c:
        jobs, users = [], {}
        for j in c.execute("SELECT * FROM jobs ORDER BY rowid DESC").fetchall():
            owner, workers, prog, anon = j["emp"] == phone, [], {}, 0
            for a in c.execute("SELECT worker, w, e, paid FROM acceptances WHERE job_id = ?", (j["id"],)).fetchall():
                if owner or a["worker"] == phone:
                    workers.append(a["worker"])
                    prog[a["worker"]] = {"w": a["w"], "e": a["e"], "paid": a["paid"]}
                    u = c.execute("SELECT name FROM users WHERE phone = ?", (a["worker"],)).fetchone()
                    if u:
                        users[a["worker"]] = {"name": u["name"]}
                else:
                    anon += 1
                    workers.append("*%d" % anon)
            jobs.append({"id": j["id"], "seed": bool(j["seed"]), "title": j["title"], "ename": j["ename"],
                         "emp": phone if owner else ("seed" if j["seed"] else "other"), "rate": j["rate"], "unit": j["unit"],
                         "units": j["units"], "need": j["need"], "lat": j["lat"], "lng": j["lng"], "dy": j["dy"], "dx": j["dx"],
                         "workers": workers, "prog": prog})
        w = c.execute("SELECT b, c FROM wallets WHERE phone = ?", (phone,)).fetchone()
        txs = [dict(p=phone, d=r["d"], a=r["a"], k=r["k"], t=r["t"]) for r in
               c.execute("SELECT d, a, k, t FROM tx WHERE phone = ? ORDER BY id DESC LIMIT 15", (phone,))]
        rows = c.execute("SELECT * FROM (SELECT * FROM chain ORDER BY idx DESC LIMIT 60) ORDER BY idx").fetchall()
        chain = [{"index": r["idx"], "time": r["time"], "data": json.loads(r["data"]), "prev": r["prev"], "hash": r["hash"]} for r in rows]
        tampered = c.execute("SELECT 1 FROM kv WHERE key = 'tamper'").fetchone() is not None
    return {"jobs": jobs, "wallet": {"b": w["b"], "c": w["c"]} if w else {"b": 0, "c": 0}, "tx": txs, "chain": chain, "users": users, "tampered": tampered}

# ---------- ledger checks ----------
def verify_chain():
    with connect() as c:
        rows = c.execute("SELECT * FROM chain ORDER BY idx").fetchall()
    prev = "0"
    for r in rows:
        if r["prev"] != prev or r["hash"] != _hash(r["idx"], r["time"], r["data"], r["prev"]):
            return {"ok": False, "msg": "Tampering detected at block %d. The chain is broken from here on." % r["idx"]}
        prev = r["hash"]
    return {"ok": True, "msg": "Chain is valid. All %d blocks link correctly and every hash matches." % len(rows)}

def tamper_demo():
    with _tx() as c:
        if c.execute("SELECT 1 FROM kv WHERE key = 'tamper'").fetchone():
            raise ValueError("A record is already edited. Verify the chain or undo the edit.")
        r = c.execute("SELECT idx, data FROM chain WHERE idx > 0 AND data LIKE '%\"amount\"%' ORDER BY idx LIMIT 1").fetchone()
        if not r:
            raise ValueError("Make a payment first, then try to tamper with it")
        d = json.loads(r["data"])
        d["amount"] += 1000
        c.execute("INSERT INTO kv (key, value) VALUES ('tamper', ?)", (json.dumps({"idx": r["idx"], "data": r["data"]}),))
        c.execute("UPDATE chain SET data = ? WHERE idx = ?", (_canon(d), r["idx"]))
    return {"msg": "Block %d amount edited. Now press Verify chain." % r["idx"]}

def restore_demo():
    with _tx() as c:
        row = c.execute("SELECT value FROM kv WHERE key = 'tamper'").fetchone()
        if row:
            v = json.loads(row["value"])
            c.execute("UPDATE chain SET data = ? WHERE idx = ?", (v["data"], v["idx"]))
            c.execute("DELETE FROM kv WHERE key = 'tamper'")

init_db()

if __name__ == "__main__":
    a = sys.argv[1:]
    try:
        if a[:1] == ["add"] and len(a) == 4:
            print("Saved:", add_user(a[1], a[2], a[3]))
        elif a[:1] == ["find"] and len(a) == 2:
            print(get_user(a[1]) or "No such user")
        elif a[:1] == ["list"]:
            for u in list_users():
                print(u["phone"], u["name"], u["role"], u["created_at"])
        else:
            print(__doc__)
    except ValueError as e:
        print("Error:", e)