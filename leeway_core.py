"""Motor de cálculo de Leeway Calculator (réplica fiel del programa original, validada contra él)."""
import math, re, struct
from functools import lru_cache

def f32(x):
    try:
        return struct.unpack('f', struct.pack('f', x))[0]
    except OverflowError:
        return math.inf if x > 0 else -math.inf

HR, EZ = 16, 2
VALID_MODS = {"NF", "EZ", "HT", "HD", "HR", "DT", "NC", "FL", "SO", "SD", "PF", "TD", "NM"}
BEST_COMBOS = ["HDNCHRFL", "HDNCFL", "HDHRFL", "HDFL", "EZHDNCFL", "EZHDFL", "EZHDHTFL", "HDHTFL", "HDHTHRFL"]

# ---------------------------------------------------------------- mods
def parse_mods(s):
    s = (s or "").upper().replace(",", "").replace(" ", "")
    if len(s) < 2 or len(s) % 2:
        return []
    out = [s[i:i + 2] for i in range(0, len(s), 2)]
    return [m for m in out if m in VALID_MODS and m != "NM"]

def mods_str(mods):
    return "".join(mods) or "NM"

def adjust_time(mods):
    for m in mods:
        if m in ("DT", "NC"): return 1.5
        if m == "HT": return 0.75
    return 1.0

def diff_mod(mods):
    for m in mods:
        if m == "HR": return HR
        if m == "EZ": return EZ
    return 0

def mod_multiplier(mods):
    r = 1.0
    for m in mods:
        if m in ("NF", "EZ"): r *= 0.5
        elif m == "HT": r *= 0.3
        elif m in ("HD", "HR"): r *= 1.06
        elif m in ("DT", "NC", "FL"): r *= 1.12
        elif m == "SO": r *= 0.9
    return r

def same_mods(a, b):
    norm = lambda l: sorted("DT" if m == "NC" else m for m in l)
    return norm(a) == norm(b)

# ---------------------------------------------------------------- spinner maths
@lru_cache(maxsize=4096)
def calc_rotations(length, adjust):
    accel = f32(8.0000000000000007e-05 + max(0.0, f32(5000.0 - f32(length))) / 1000.0 / 2000.0)
    accel = f32(accel / adjust)
    frames = int(length - math.floor(16.666666666666668 * adjust))
    t = rot = 0.0
    for _ in range(frames):
        t = f32(t + accel)
        rot = f32(rot + f32(min(t, 0.050000000000000003) / 3.1415926535897931))
    return rot

def calc_rot_req(length, od, dmod):
    if dmod == HR: od = min(10.0, od * 1.4)
    elif dmod == EZ: od = od / 2
    rate = 2.5 + 0.5 * od if od > 5 else 3 + 0.4 * od
    return int(f32(f32(length) / 1000.0) * rate)

def calc_leeway(length, adjust, od, dmod):
    req = calc_rot_req(length, od, dmod)
    rot = calc_rotations(length, adjust)
    if req % 2 != 0 and math.floor(rot) % 2 != 0:
        return rot - math.floor(rot) + 1
    return rot - math.floor(rot)

def calc_amount(rot_int, req):
    extra = float(max(0, rot_int - (req + 3)))
    if req % 2 > 0: return f"{int(math.floor(extra / 2))}k (F)"
    if extra % 2 == 0: return f"{int(extra / 2)}k (T)"
    return f"{int(math.floor(extra / 2))}k+100 (T)"

def calc_spin_bonus(length, od, adjust, dmod):
    rot = int(calc_rotations(length, adjust))
    req = calc_rot_req(length, od, dmod)
    base = int(math.floor(rot / 2.0)) * 100 if req % 2 == 0 else ((req + 3) // 2) * 100
    return base + int(math.floor((rot - (req + 3)) / 2.0)) * 1100

# ---------------------------------------------------------------- .osu parsing
class Beatmap:
    def __init__(self, text):
        self.meta, self.diff = {}, {}
        self.version, self.breaks, self.tp, self.objs = 14, [], [], []
        m = re.search(r"osu file format v(\d+)", text)
        if m: self.version = int(m.group(1))
        sec = ""
        for raw in text.replace("\r", "\n").split("\n"):
            line = raw.strip()
            if not line or line.startswith("//"): continue
            if line.startswith("["): sec = line.strip("[]"); continue
            if sec in ("Metadata", "Difficulty"):
                k, _, v = line.partition(":")
                (self.meta if sec == "Metadata" else self.diff)[k.strip()] = v.strip()
            elif sec == "Events":
                p = line.split(",")
                if len(p) == 3 and p[0] in ("2", "Break"):
                    self.breaks.append(int(float(p[2])) - int(float(p[1])))
            elif sec == "TimingPoints":
                p = line.split(",")
                if len(p) > 1: self.tp.append([float(p[0]), float(p[1])])
            elif sec == "HitObjects":
                self.objs.append(line.split(","))
        for t in self.tp:                     # igual que el original: punto en t=0 con el primer beatLength rojo
            if t[1] > 0:
                self.tp.insert(0, [0.0, t[1]]); break
        g = lambda k, d: f32(float(self.diff.get(k, d)))
        self.hp, self.cs, self.od = g("HPDrainRate", 5), g("CircleSize", 5), g("OverallDifficulty", 5)
        self.slider_mult = float(self.diff.get("SliderMultiplier", 1.4))
        self.tick_rate = float(self.diff.get("SliderTickRate", 1))
        if not self.objs: raise ValueError("El mapa no tiene hit objects.")

    @staticmethod
    def obj_type(t):
        b = format(int(t), "b").zfill(8)[-8:]
        return 3 if b[4] == "1" else 1 if b[6] == "1" else 0

    def beat_length_at(self, time):
        bl, sv = 0.0, -100.0
        for t, v in self.tp:
            if time >= t:
                if v > 0: bl, sv = v, -100.0
                else: sv = v
        return bl, sv

    def tick_count(self, plen, slides, bl, sv):
        clamp = min(max(abs(sv), 10.0), 1000.0)
        dur = clamp * plen * bl / (self.slider_mult * 10000.0)
        step = bl / self.tick_rate
        if self.version < 8: step *= clamp / 100.0
        if step <= 0: return 0
        rem, n = dur - step, 0
        while not rem < 10.0:
            n += 1; rem -= step
        return n * slides

    def drain_ms(self):
        return int(self.objs[-1][2]) - int(self.objs[0][2]) - sum(self.breaks)

    def spinners(self):
        return [(int(o[2]), int(o[5])) for o in self.objs if self.obj_type(o[3]) == 3]

    def max_score(self, mods):
        adj, dm = adjust_time(mods), diff_mod(mods)
        drain = self.drain_ms() // 1000
        density = 16.0 if drain <= 0 else min(max(f32(f32(f32(len(self.objs)) / f32(drain)) * 8), 0.0), 16.0)
        pts = int(round(((self.hp + self.od + self.cs + density) / 38.0) * 5))
        mm = pts * mod_multiplier(mods)
        score = bonus = combo = 0
        hit = lambda: 300 + int(max(0, combo - 1) * (12.0 * mm))
        for o in self.objs:
            t = self.obj_type(o[3])
            if t == 0:
                score += hit(); combo += 1
            elif t == 1:
                bl, sv = self.beat_length_at(int(o[2]))
                slides = int(o[6])
                ticks = self.tick_count(float(o[7]), slides, bl, sv)
                bonus += ticks * 10 + (slides + 1) * 30
                combo += ticks + slides + 1
                score += hit()
            else:
                score += hit()
                bonus += calc_spin_bonus(int(o[5]) - int(o[2]), self.od, adj, dm)
                combo += 1
        return score + bonus

    def best_combo(self):
        best = max(BEST_COMBOS, key=lambda c: self.max_score(parse_mods(c)))
        return best

    def spinner_table(self, mods):
        adj, dm = adjust_time(mods), diff_mod(mods)
        rows = []
        for i, (s, e) in enumerate(self.spinners(), 1):
            length = e - s
            rot = calc_rotations(length, adj)
            req = calc_rot_req(length, self.od, dm)
            rows.append(dict(n=i, start=s, length=length, rotations=round(rot, 5), req=req,
                             amount=calc_amount(int(rot), req),
                             leeway=round(calc_leeway(length, adj, self.od, dm), 5)))
        return rows

    def info(self):
        m = self.meta
        return dict(title=m.get("Title", "?"), artist=m.get("Artist", "?"), version=m.get("Version", "?"),
                    creator=m.get("Creator", "?"), hp=round(self.hp, 2), cs=round(self.cs, 2), od=round(self.od, 2),
                    objects=len(self.objs), spinners=len(self.spinners()),
                    drain=max(0, self.drain_ms() // 1000))

# ---------------------------------------------------------------- ranking (old.ppy.sh/b/<id>)
FLAG = re.compile(r"flags/([a-z]{2})\.gif", re.I)

def _cells(row):
    return re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)

def parse_leaderboard(html, limit=8):
    out = []
    for row in re.findall(r"<tr class='row[12]p'>.*?</tr>", html, re.S):
        c = _cells(row)
        if len(c) < 11: continue
        strip = lambda s: re.sub(r"<[^>]+>", "", s).replace("&nbsp;", " ").replace("&nbsp", " ").strip()
        try:
            hits = [int(x) for x in re.findall(r"\d+", strip(c[6]))][:3]
            fl = FLAG.search(c[4]); uid = re.search(r"/u/(\d+)", c[4])
            name = strip(re.sub(r"<img[^>]*>", "", c[4]))
            mods_raw = strip(c[10])
            out.append(dict(rank=int(re.search(r"\d+", strip(c[0])).group()),
                            grade=(re.search(r"/([A-Z]+H?)_small", c[1]) or [None, "?"])[1],
                            score=int(re.sub(r"\D", "", strip(c[2]))),
                            acc=strip(c[3]), player=name, uid=uid.group(1) if uid else None,
                            country=fl.group(1).upper() if fl else "", combo=int(strip(c[5])),
                            n300=hits[0], n100=hits[1], n50=hits[2], geki=int(strip(c[7])),
                            katu=int(strip(c[8])), miss=int(strip(c[9])),
                            mods=[] if mods_raw in ("None", "") else parse_mods(mods_raw)))
        except (ValueError, AttributeError, TypeError, IndexError):
            continue
        if len(out) >= limit: break
    return out

def judge(bm, p):
    """Compara la puntuación del jugador con el máximo calculado para SUS mods."""
    mods = [m for m in p["mods"] if m not in ("SD", "PF", "TD")]
    mx = bm.max_score(mods)
    clean = p["n100"] == 0 and p["n50"] == 0 and p["miss"] == 0
    d = p["score"] - mx
    if d == 0: st = "capped"
    elif d > 0: st = "over"
    elif clean: st = "not"
    else: st = "unknown"
    return dict(max=mx, diff=d, status=st, clean=clean, mods_used=mods_str(mods))
