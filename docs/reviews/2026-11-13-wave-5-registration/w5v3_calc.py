"""Wave 5 registration v3: every figure changed from v2. Standard library only.

Run: python3 -I w5v3_calc.py > w5v3_calc.out.txt   (seeds 20261113 + k)
"""
import hashlib
import math
import random
from statistics import NormalDist

N01 = NormalDist()
SEED = 20261113


def h(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def section(t):
    print()
    print("=" * 8, t)


# ------------------------------------------------------------ 1. lists (unchanged, re-checked)
section("1. C1 in C2 order and L2, recomputed")
C1 = ["gorilla/mux", "jpadilla/pyjwt", "rs/zerolog", "hynek/structlog", "pelletier/go-toml",
      "jd/tenacity", "sirupsen/logrus", "tox-dev/filelock", "marshmallow-code/marshmallow",
      "hashicorp/go-version", "urfave/cli", "more-itertools/more-itertools"]
c1 = sorted(C1, key=lambda r: (h("crb.d3.repo|20261112|" + r), r))
print("sha256(C1 in C2 order) =", h("".join(r + "\n" for r in c1)),
      "match:", h("".join(r + "\n" for r in c1)) ==
      "b38fb8b6b8de3bf50ebc88b54e6dd54c1d9578bc2c5209c47fcc8350a612a1de")
L2 = ["labstack/echo", "mahmoud/boltons", "BurntSushi/toml", "python-poetry/tomlkit",
      "astanin/python-tabulate", "arrow-py/arrow", "andialbrecht/sqlparse", "pypa/packaging",
      "tox-dev/platformdirs", "go-chi/chi", "google/go-cmp"]
l2 = sorted(L2, key=lambda r: (h("crb.w5.repo|20261113|" + r), r))
print("L2 order unchanged:", l2 == L2)
print("sha256(L2 in hash order) =", h("".join(r + "\n" for r in l2)),
      "match:", h("".join(r + "\n" for r in l2)) ==
      "c62cf5f1f39b336e9842b43beb9794cf848051bb84078ba1331213bfa84e8145")
print("seeded-order key example (R11 item 5, Wave 4 part 2 step 2):",
      "crb.reading.v1|<repo>|<cell key>|<commit>")

# ------------------------------------------------------------ 2. costs
section("2. Costs, product dollars, unconfirmed")
RATE = 48.115522 / 120
LEFT = 200 - 69.98
HIGHX = 2.5
PILOT = 8
print(f"rate per commit-arm (2 attempts) = 48.115522/120 = {RATE:.6f}; left = {LEFT:.2f}")
print(f"high per full repository = 6 commits x 2 arms x {RATE:.6f} x 2.5 = "
      f"{12 * RATE * HIGHX:.4f}")
print(f"pilot high = 8 x {RATE:.6f} x 2.5 = {PILOT * RATE * HIGHX:.4f}")
print(" n | commit-arms | central  | high     | line(ceil high) | lift over 130.02")
for n in range(6, 13):
    ca = n * 6 * 2 + PILOT
    c = ca * RATE
    hi = c * HIGHX
    line = math.ceil(hi)
    print(f"{n:2d} | {ca:11d} | {c:8.2f} | {hi:8.2f} | {line:15d} | {max(0, line - LEFT):.2f}"
          f"  (high minus 130.02 = {hi - LEFT:+.2f})")
print("thinnest R11 repository (1 XS + 1 S): 2 commits x 2 arms =",
      f"4 commit-arms, central {4 * RATE:.2f}, high {4 * RATE * HIGHX:.2f}")
LINE = 129
print("repository-boundary stop with line 129: start repository j only if spend + 12.0289 <= 129")
for k in range(0, 11):
    spend_hi = PILOT * RATE * HIGHX + k * 12 * RATE * HIGHX
    print(f"  after pilot + {k:2d} repos at high: spend {spend_hi:7.2f}; next starts: "
          f"{spend_hi + 12 * RATE * HIGHX <= LINE}")
per = 10.06 * 60 / (49 * 5)
for n in (6, 10):
    ca = n * 12 + PILOT
    print(f"time D3 n={n}: {ca} commit-arms x 2 x {per:.3f} min = {ca * 2 * per / 60:.1f} h")
# alternatives not taken
def alt(name, n, m, arms, pilot):
    ca = n * m * arms + pilot
    c = ca * RATE
    hi = c * HIGHX
    print(f"{name}: {ca} commit-arms, central {c:.2f}, high {hi:.2f}, line {math.ceil(hi)}, "
          f"lift {max(0, math.ceil(hi) - LEFT):.2f}")
alt("D1 n=10 m=10 (A0,S1)", 10, 10, 2, 8)
alt("D1 n=7  m=10 (A0,S1)", 7, 10, 2, 8)
alt("D2 n=10 m=10 (A0,S1,W; pilot 10 commits x 4 arms)", 10, 10, 3, 40)
alt("D2 n=7  m=10 (A0,S1,W; pilot 10 commits x 4 arms)", 7, 10, 3, 40)
print("D2 S1 attempts n=10: (100 + 10) x 2 =", (100 + 10) * 2,
      f"; author central = {220 * 0.174468 / 126:.3f}")

# ------------------------------------------------------------ 3. exact sign-flip machinery
def signflip_p(xs):
    """Exact two-sided sign-flip p over all 2^n patterns (Gray-code walk)."""
    n = len(xs)
    obs = abs(sum(xs)) - 1e-9
    s = sum(xs)  # all signs +1
    signs = [1] * n
    hit = 1 if abs(s) >= obs else 0
    for i in range(1, 2 ** n):
        j = (i & -i).bit_length() - 1
        s -= 2 * signs[j] * xs[j]
        signs[j] = -signs[j]
        hit += abs(s) >= obs
    return hit / 2 ** n


def sign_test_power(n, q, alpha):
    def p_of(k):
        return min(1.0, 2 * sum(math.comb(n, j) for j in range(k, n + 1)) / 2 ** n)
    kmin = next((k for k in range(n // 2 + 1, n + 1) if p_of(k) < alpha), None)
    if kmin is None:
        return 0.0, None
    return sum(math.comb(n, k) * q ** k * (1 - q) ** (n - k) for k in range(kmin, n + 1)), kmin


section("3. Power at q = 11/12, n = 6..12, alpha 0.05 (J = 1)")
q = 11 / 12
z = N01.inv_cdf(q)
rng = random.Random(SEED + 10)
W = 4000
print("method A: exact sign test, equal magnitudes (binomial); method B: exact sign-flip,")
print(f"unit difference ~ Normal(z,1), z = Phi^-1(11/12) = {z:.4f}, {W} waves a cell, seed {SEED + 10}")
for n in range(6, 13):
    pa, kmin = sign_test_power(n, q, 0.05)
    hit = 0
    for _ in range(W):
        xs = [rng.gauss(z, 1) for _ in range(n)]
        if sum(xs) > 0 and signflip_p(xs) < 0.05:
            hit += 1
    se = math.sqrt((hit / W) * (1 - hit / W) / W)
    print(f"n={n:2d}: A {pa:.3f} (needs >= {kmin} of {n} same sign) | B {hit / W:.3f} "
          f"(MC s.e. {se:.3f}) | p_min 2/2^n = {2 / 2 ** n:.6f}")


# ------------------------------------------------------------ 4. discrete design simulation
def draw_repo(rng, m, mu0, delta, tau_e, rho=0.25, sd_mu=0.15):
    mu = min(0.95, max(0.05, rng.gauss(mu0, sd_mu)))
    k = 1 / rho - 1
    d_r = rng.gauss(delta, tau_e)
    ca = cb = 0
    for _ in range(m):
        p = rng.betavariate(mu * k, (1 - mu) * k)
        pl = min(1.0, max(0.0, p + d_r))
        ca += (rng.random() < p) + (rng.random() < p)
        cb += (rng.random() < pl) + (rng.random() < pl)
    return 100 * (cb - ca) / (2 * m)


TQ95 = {}


def t_q95(df):
    if df not in TQ95:
        # bisection on the t cdf via numeric integration of the density (Simpson)
        def pdf(t):
            return math.exp(math.lgamma((df + 1) / 2) - math.lgamma(df / 2)) / math.sqrt(
                df * math.pi) * (1 + t * t / df) ** (-(df + 1) / 2)

        def cdf(t):
            N = 4000
            a, b = 0.0, t
            hh = (b - a) / N
            s = pdf(a) + pdf(b)
            for i in range(1, N):
                s += (4 if i % 2 else 2) * pdf(a + i * hh)
            return 0.5 + s * hh / 3
        lo, hi = 0.0, 10.0
        for _ in range(60):
            mid = (lo + hi) / 2
            if cdf(mid) < 0.95:
                lo = mid
            else:
                hi = mid
        TQ95[df] = (lo + hi) / 2
    return TQ95[df]


def read_word(xs, usable_ok=True):
    n = len(xs)
    nz = sum(1 for x in xs if abs(x) > 1e-12)
    mean = sum(xs) / n
    p = signflip_p(xs)
    if p < 0.05:
        return ("Better" if mean > 0 else "Worse"), p, nz
    sd = math.sqrt(sum((x - mean) ** 2 for x in xs) / (n - 1))
    half = t_q95(n - 1) * sd / math.sqrt(n)
    if usable_ok and nz >= 6 and mean - half > -15 and mean + half < 15:
        return "Within 15", p, nz
    return "Undecided", p, nz


section("4. Discrete simulation of the D3 read, n = 6..12 (model as v2 appendix A part 6)")
print("A0 repo mean ~ N(0.7,0.15) clipped; commit chance Beta, ICC 0.25; S1 shift per repo")
print("~ N(delta, tau_e); 2 attempts/arm; m = 6; 1,000 waves a cell; seed", SEED + 20)
print("cols: P(correct Better/Worse) | P(Within 15) | P(Undecided) | P(Undecided and n' < 6)"
      " | P(wrong-sign decisive)")
rng = random.Random(SEED + 20)
WAV = 1000
for tau_e in (0.10, 0.20):
    for delta in (0.0, -0.25, -0.46):
        for n in range(6, 13):
            dec = w15 = und = und_few = wrong = 0
            for _ in range(WAV):
                xs = [draw_repo(rng, 6, 0.7, delta, tau_e) for _ in range(n)]
                word, p, nz = read_word(xs)
                if word in ("Better", "Worse"):
                    right = (word == "Worse") if delta < 0 else False
                    if delta == 0:
                        wrong += 1
                    elif right:
                        dec += 1
                    else:
                        wrong += 1
                elif word == "Within 15":
                    w15 += 1
                else:
                    und += 1
                    und_few += nz < 6
            print(f"tau_e={tau_e:.2f} delta={delta:+.2f} n={n:2d}: {dec / WAV:.3f} | "
                  f"{w15 / WAV:.3f} | {und / WAV:.3f} | {und_few / WAV:.3f} | {wrong / WAV:.3f}")

section("5. One thin R11 repository (m_r = 2: one XS, one S) among n = 7, tau_e 0.10")
rng = random.Random(SEED + 30)
for delta in (0.0, -0.46):
    for thin in (0, 1):
        dec = w15 = 0
        for _ in range(WAV):
            xs = [draw_repo(rng, 2 if i < thin else 6, 0.7, delta, 0.10) for i in range(7)]
            word, p, nz = read_word(xs)
            dec += word == "Worse" and delta < 0
            w15 += word == "Within 15"
        print(f"delta={delta:+.2f} thin repos={thin}: P(Worse)={dec / WAV:.3f} "
              f"P(Within 15)={w15 / WAV:.3f}")

# ------------------------------------------------------------ 6. known-answer sets
section("6. Known-answer sets K1..K7 through the registered word rule (J = 1)")
K = {
    "K1 eight repos all -50": ([-50.0] * 8, True),
    "K2 eight repos +-10 alternating": ([10.0, -10.0] * 4, True),
    "K3 six repos, one 0, five -40": ([0.0] + [-40.0] * 5, True),
    "K4 seven repos all +30": ([30.0] * 7, True),
    "K5 ten repos, nine -20 one +10": ([-20.0] * 9 + [10.0], True),
    "K6 = K2 with usable-test share 0.85 (P3 fails)": ([10.0, -10.0] * 4, False),
}
for name, (xs, ok) in K.items():
    n = len(xs)
    mean = sum(xs) / n
    sd = math.sqrt(sum((x - mean) ** 2 for x in xs) / (n - 1))
    word, p, nz = read_word(xs, ok)
    print(f"{name}: D={mean:+.4f} p={p:.7f} ({round(p * 2 ** n)}/{2 ** n}) nonzero={nz} "
          f"90% half-width={t_q95(n - 1) * sd / math.sqrt(n):.4f} -> {word}")
# K7: row level, unequal counts
rows = [("r1", 2, 3, 1)] + [(f"r{i}", 6, 9, 5) for i in range(2, 7)]
xs = []
for r, m, a0, s1 in rows:
    d = 100 * (s1 / (2 * m) - a0 / (2 * m))
    xs.append(d)
    print(f"K7 {r}: m_r={m}, registered rows/arm={2 * m}, A0 clean={a0}, S1 clean={s1}, "
          f"D_r={d:+.4f}")
word, p, nz = read_word(xs)
mean = sum(xs) / len(xs)
sd = math.sqrt(sum((x - mean) ** 2 for x in xs) / (len(xs) - 1))
print(f"K7 six repos, unequal counts: D={mean:+.4f} p={p:.7f} ({round(p * 64)}/64) "
      f"nonzero={nz} 90% half-width={t_q95(5) * sd / math.sqrt(6):.4f} -> {word}")
print("check t(0.95,5) =", round(t_q95(5), 4), " t(0.95,7) =", round(t_q95(7), 4),
      " t(0.95,9) =", round(t_q95(9), 4))
