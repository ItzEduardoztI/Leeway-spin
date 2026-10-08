"""Leeway Calculator (web) - con "Iniciar sesion con osu!". Solo usa la libreria estandar de Python."""
import json, os, re, secrets, threading, time, urllib.error, urllib.parse, urllib.request
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from leeway_core import Beatmap, parse_mods, mods_str, judge

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("PORT", "8765"))
BASE_URL = os.environ.get("BASE_URL", "http://localhost:%d" % PORT).rstrip("/")
CLIENT_ID = os.environ.get("OSU_CLIENT_ID", "").strip()
CLIENT_SECRET = os.environ.get("OSU_CLIENT_SECRET", "").strip()
OSU = os.environ.get("OSU_API_BASE", "https://osu.ppy.sh").rstrip("/")
OLD = os.environ.get("OSU_OLD_BASE", "https://old.ppy.sh").rstrip("/")
RATE = int(os.environ.get("LEEWAY_RATE", "40"))          # analisis por minuto y por IP
SECURE = BASE_URL.startswith("https://")
UA = "LeewayCalculator/3 (by TheJorgeMC)"
CONFIGURED = bool(CLIENT_ID and CLIENT_SECRET)
INDEX = open(os.path.join(HERE, "index.html"), "rb").read()


MSG = {
    "bad_input": ("Invalid beatmap ID or link.", "ID o link de beatmap no válido."),
    "map_fail": ("Couldn't download beatmap {id} ({err}).", "No pude descargar el mapa {id} ({err})."),
    "file_big": ("The .osu file is too large.", "El archivo .osu es demasiado grande."),
    "no_objects": ("This beatmap has no hit objects.", "El mapa no tiene hit objects."),
    "bad_file": ("Couldn't read this beatmap.", "No pude leer este mapa."),
    "no_id": ("This beatmap has no ID, so the ranking can't be loaded.", "Sin ID de beatmap no se puede cargar el ranking."),
    "rank_na": ("Ranking not available right now.", "Ranking no disponible por ahora."),
    "rank_err": ("Ranking not available ({err}).", "Ranking no disponible ({err})."),
    "no_scores": ("This beatmap has no scores in the ranking.", "Este mapa no tiene scores en el ranking."),
    "origin": ("Origin not allowed.", "Origen no permitido."),
    "rate": ("Too many requests.", "Demasiadas consultas seguidas."),
    "generic": ("Something went wrong analyzing this beatmap.", "Algo salió mal al analizar este mapa."),
}


def msg(key, lang, **kw):
    return MSG[key][1 if lang == "es" else 0].format(**kw)


class UserError(Exception):
    def __init__(self, key, **kw):
        Exception.__init__(self, key); self.key, self.kw = key, kw


class ApiError(Exception):
    def __init__(self, code, msg):
        Exception.__init__(self, "HTTP %s %s" % (code, msg)); self.code = code


def http(url, data=None, token=None, timeout=20):
    headers = {"User-Agent": UA, "Accept": "application/json"}
    body = None
    if data is not None:
        body = json.dumps(data).encode(); headers["Content-Type"] = "application/json"
    if token: headers["Authorization"] = "Bearer " + token
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=body, headers=headers), timeout=timeout) as r:
            return r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        raise ApiError(e.code, e.read().decode("utf-8", "replace")[:160])


# ------------------------------------------------------------------ tokens y sesiones
_app = {"tok": None, "exp": 0.0}
_lock = threading.Lock()
SESSIONS = {}


def app_token():
    with _lock:
        if _app["tok"] and time.time() < _app["exp"]: return _app["tok"]
        o = json.loads(http(OSU + "/oauth/token", {"client_id": int(CLIENT_ID), "client_secret": CLIENT_SECRET,
                                                   "grant_type": "client_credentials", "scope": "public"}))
        _app["tok"], _app["exp"] = o["access_token"], time.time() + max(60, o.get("expires_in", 3600) - 300)
        return _app["tok"]


def user_token(s):
    if time.time() < s["exp"]: return s["access"]
    o = json.loads(http(OSU + "/oauth/token", {"client_id": int(CLIENT_ID), "client_secret": CLIENT_SECRET,
                                               "grant_type": "refresh_token", "refresh_token": s["refresh"]}))
    s["access"], s["refresh"] = o["access_token"], o.get("refresh_token", s["refresh"])
    s["exp"] = time.time() + max(60, o.get("expires_in", 3600) - 300)
    return s["access"]


def make_session(code):
    o = json.loads(http(OSU + "/oauth/token", {"client_id": int(CLIENT_ID), "client_secret": CLIENT_SECRET, "code": code,
                                               "grant_type": "authorization_code", "redirect_uri": BASE_URL + "/callback"}))
    me = json.loads(http(OSU + "/api/v2/me", token=o["access_token"]))
    if len(SESSIONS) > 5000:
        for k in sorted(SESSIONS, key=lambda k: SESSIONS[k]["t"])[:1000]: SESSIONS.pop(k, None)
    sid = secrets.token_urlsafe(32)
    SESSIONS[sid] = dict(id=me["id"], name=me["username"], access=o["access_token"], refresh=o.get("refresh_token", ""),
                         exp=time.time() + max(60, o.get("expires_in", 3600) - 300), t=time.time())
    return sid


# ------------------------------------------------------------------ datos de osu!
_maps, _lb = {}, {}


def fetch_map(bid):
    c = _maps.get(bid)
    if c and time.time() - c[0] < 3600: return c[1]
    err = None
    for base in (OLD, OSU):
        try:
            txt = http("%s/osu/%d" % (base, bid))
            if "[HitObjects]" in txt:
                if len(_maps) > 300: _maps.clear()
                _maps[bid] = (time.time(), txt); return txt
        except Exception as e:
            err = e
    raise UserError("map_fail", id=bid, err=err)


def parse_v2(s, rank):
    g = lambda o, k: o.get(k) if isinstance(o, dict) else None
    num = lambda v: float(v) if isinstance(v, (int, float)) else 0.0
    u, st = g(s, "user") or {}, g(s, "statistics") or {}
    pick = lambda a, b: int(num(st.get(a, st.get(b))))
    sc = num(g(s, "legacy_total_score")) or num(g(s, "score")) or num(g(s, "total_score"))
    acc = num(g(s, "accuracy")); acc = acc * 100 if acc <= 1 else acc
    uid = int(num(u.get("id")) or num(g(s, "user_id")))
    mods = "".join(m if isinstance(m, str) else str(g(m, "acronym") or "") for m in (g(s, "mods") or []))
    return dict(rank=rank, grade=g(s, "rank") or "?", score=int(sc), acc="%.2f%%" % acc, player=u.get("username") or "(sin nombre)",
                uid=str(uid) if uid else None, country=(u.get("country_code") or "").upper(), combo=int(num(g(s, "max_combo"))),
                n300=pick("count_300", "great"), n100=pick("count_100", "ok"), n50=pick("count_50", "meh"),
                miss=pick("count_miss", "miss"), geki=pick("count_geki", "perfect"), katu=pick("count_katu", "good"),
                mods=parse_mods(mods))


def top_scores(bid, limit=50):
    c = _lb.get(bid)
    if c and time.time() - c[0] < 300: return c[1]
    o = json.loads(http("%s/api/v2/beatmaps/%d/scores?mode=osu&type=global&legacy_only=1" % (OSU, bid), token=app_token()))
    rows = [parse_v2(s, i + 1) for i, s in enumerate((o.get("scores") or [])[:limit])]
    if len(_lb) > 500: _lb.clear()
    _lb[bid] = (time.time(), rows); return rows


def my_score(bid, sess):
    try:
        o = json.loads(http("%s/api/v2/beatmaps/%d/scores/users/%s?mode=osu&legacy_only=1" % (OSU, bid, sess["id"]), token=user_token(sess)))
        return parse_v2(o.get("score") or o, int(o.get("position") or 0))
    except Exception:
        return None


def decorate(bm, p):
    p = dict(p); p.update(judge(bm, p))
    mods = parse_mods(p["mods_used"]) if p["mods_used"] != "NM" else []
    rows = bm.spinner_table(mods)
    p["rot_total"] = round(sum(r["rotations"] for r in rows), 1); p["req_total"] = sum(r["req"] for r in rows)
    p["lost_est"] = round(-p["diff"] / 1100.0, 1) if p["clean"] and p["diff"] < 0 else None
    p["mods"] = mods_str(p["mods"]); return p


def analyze(req, sess, lang="en"):
    text, bid = req.get("osu_text"), None
    q, mods_in = (req.get("input") or "").strip(), (req.get("mods") or "").upper()
    if text:
        if len(text) > 3_000_000: raise UserError("file_big")
    else:
        m = re.search(r"osu/(\d+)", q) or re.search(r"/b/(\d+)", q) or re.match(r"^\s*(\d+)", q)
        if not m: raise UserError("bad_input")
        bid = int(m.group(1))
        tail = re.search(r"([A-Za-z]+)$", q)
        if tail and not mods_in: mods_in = tail.group(1).upper()
        text = fetch_map(bid)
    bm = Beatmap(text)
    if not bid:
        m = re.search(r"BeatmapID:\s*(\d+)", text); bid = int(m.group(1)) if m and int(m.group(1)) > 0 else None
    auto = mods_in in ("", "AUTO")
    mods = parse_mods(bm.best_combo() if auto else mods_in)
    out = dict(map=bm.info(), beatmap_id=bid, mods=mods_str(mods), auto=auto, max_score=bm.max_score(mods),
               spinners=bm.spinner_table(mods), players=[], me_score=None, warning=None)
    if not bid: out["warning"] = msg("no_id", lang)
    elif not CONFIGURED: out["warning"] = msg("rank_na", lang)
    else:
        try:
            out["players"] = [decorate(bm, p) for p in top_scores(bid)]
            if not out["players"]: out["warning"] = msg("no_scores", lang)
        except Exception as e:
            out["warning"] = msg("rank_err", lang, err=e)
        if sess:
            mine = [p for p in out["players"] if p.get("uid") == str(sess["id"])]
            if mine: mine[0]["is_me"] = True
            else:
                ms = my_score(bid, sess)
                if ms: out["me_score"] = decorate(bm, ms)
    return out


# ------------------------------------------------------------------ servidor
_hits = {}


def rate_ok(ip):
    now = time.time(); h = [t for t in _hits.get(ip, []) if now - t < 60]
    if len(h) >= RATE: _hits[ip] = h; return False
    h.append(now); _hits[ip] = h
    if len(_hits) > 5000: _hits.clear()
    return True


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def send(self, code, body, ctype="application/json; charset=utf-8", headers=()):
        if isinstance(body, (dict, list)): body = json.dumps(body)
        if isinstance(body, str): body = body.encode()
        self.send_response(code)
        for k, v in (("Content-Type", ctype), ("Content-Length", str(len(body))), ("Cache-Control", "no-store"),
                     ("X-Content-Type-Options", "nosniff"), ("X-Frame-Options", "DENY"), ("Referrer-Policy", "same-origin"),
                     ("Content-Security-Policy", "default-src 'self'; img-src 'self' https://a.ppy.sh data:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; frame-ancestors 'none'")):
            self.send_header(k, v)
        for k, v in headers: self.send_header(k, v)
        self.end_headers(); self.wfile.write(body)

    def redirect(self, url, cookies=()):
        self.send(302, b"", "text/plain", [("Location", url)] + [("Set-Cookie", c) for c in cookies])

    def cookie(self, name, value, age):
        return "%s=%s; Path=/; Max-Age=%d; HttpOnly; SameSite=Lax%s" % (name, value, age, "; Secure" if SECURE else "")

    def session(self):
        try: sid = SimpleCookie(self.headers.get("Cookie", "")).get("sid")
        except Exception: return None
        return SESSIONS.get(sid.value) if sid else None

    def ip(self):
        return (self.headers.get("X-Forwarded-For", "").split(",")[0].strip() or self.client_address[0])

    def do_GET(self):
        u = urllib.parse.urlparse(self.path); q = urllib.parse.parse_qs(u.query)
        if u.path == "/": return self.send(200, INDEX, "text/html; charset=utf-8")
        if u.path == "/healthz": return self.send(200, "ok", "text/plain")
        if u.path == "/api/me":
            s = self.session()
            return self.send(200, dict(configured=CONFIGURED, logged_in=bool(s), username=s["name"] if s else None, id=s["id"] if s else None))
        if u.path == "/login":
            if not CONFIGURED: return self.redirect("/?login_error=1")
            st = secrets.token_urlsafe(16)
            url = OSU + "/oauth/authorize?" + urllib.parse.urlencode(dict(client_id=CLIENT_ID, redirect_uri=BASE_URL + "/callback",
                                                                           response_type="code", scope="public identify", state=st))
            return self.redirect(url, [self.cookie("st", st, 600)])
        if u.path == "/callback":
            try: st = SimpleCookie(self.headers.get("Cookie", "")).get("st")
            except Exception: st = None
            code, state = (q.get("code") or [""])[0], (q.get("state") or [""])[0]
            if not (CONFIGURED and code and st and secrets.compare_digest(st.value, state)):
                return self.redirect("/?login_error=1", [self.cookie("st", "", 0)])
            try: sid = make_session(code)
            except Exception: return self.redirect("/?login_error=1", [self.cookie("st", "", 0)])
            return self.redirect("/", [self.cookie("sid", sid, 30 * 86400), self.cookie("st", "", 0)])
        self.send(404, "Not found", "text/plain")

    def lang(self):
        return "es" if self.headers.get("X-Lang", "en").lower().startswith("es") else "en"

    def do_POST(self):
        lang = self.lang()
        origin = self.headers.get("Origin")
        if origin and urllib.parse.urlparse(origin).netloc != self.headers.get("Host"):
            return self.send(403, dict(error=msg("origin", lang)))
        if self.path == "/logout":
            try: sid = SimpleCookie(self.headers.get("Cookie", "")).get("sid")
            except Exception: sid = None
            if sid: SESSIONS.pop(sid.value, None)
            return self.send(200, dict(ok=True), headers=[("Set-Cookie", self.cookie("sid", "", 0))])
        if self.path != "/api/analyze": return self.send(404, dict(error="Not found"))
        if not rate_ok(self.ip()): return self.send(429, dict(error=msg("rate", lang)))
        try:
            n = min(int(self.headers.get("Content-Length", 0)), 4_000_000)
            res, code = analyze(json.loads(self.rfile.read(n) or b"{}"), self.session(), lang), 200
        except UserError as e:
            res, code = dict(error=msg(e.key, lang, **e.kw)), 400
        except ValueError as e:
            res, code = dict(error=msg(str(e) if str(e) in MSG else "bad_file", lang)), 400
        except Exception:
            res, code = dict(error=msg("generic", lang)), 400
        self.send(code, res)

if __name__ == "__main__":
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), H)
    print("Leeway Calculator en %s  (login con osu!: %s)" % (BASE_URL, "activado" if CONFIGURED else "NO configurado"))
    try: srv.serve_forever()
    except KeyboardInterrupt: pass
