"""Wave 5 registration v2: every hash, p, power and cost figure. Standard library only.

Run: python3 -I w5_calc.py > w5_calc.out.txt   (seed 20261113 throughout)
"""
import hashlib
import math
import random
from statistics import NormalDist

SEED = 20261113
N01 = NormalDist()


def h(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def section(t):
    print()
    print("=" * 8, t)


# ---------------------------------------------------------------- 1. lists
section("1. C1 in C2 order (recomputed) and the second list L2")
C1 = ["gorilla/mux", "jpadilla/pyjwt", "rs/zerolog", "hynek/structlog", "pelletier/go-toml",
      "jd/tenacity", "sirupsen/logrus", "tox-dev/filelock", "marshmallow-code/marshmallow",
      "hashicorp/go-version", "urfave/cli", "more-itertools/more-itertools"]
c1 = sorted(C1, key=lambda r: (h("crb.d3.repo|20261112|" + r), r))
for i, r in enumerate(c1, 1):
    print(f"C2 {i:2d} {r:32s} {h('crb.d3.repo|20261112|' + r)}")
c1_list_hash = h("".join(r + "\n" for r in c1))
print("sha256(C1 list in C2 order) =", c1_list_hash)
print("matches the Wave 4 registration:",
      c1_list_hash == "b38fb8b6b8de3bf50ebc88b54e6dd54c1d9578bc2c5209c47fcc8350a612a1de")

SCOUT_RANKED = ["urfave/cli", "labstack/echo", "andialbrecht/sqlparse", "BurntSushi/toml",
                "tox-dev/platformdirs", "arrow-py/arrow", "spf13/pflag", "pypa/packaging",
                "python-poetry/tomlkit", "pelletier/go-toml", "more-itertools/more-itertools",
                "go-chi/chi", "google/go-cmp", "astanin/python-tabulate", "mahmoud/boltons",
                "sirupsen/logrus"]
LANG = {"labstack/echo": "Go", "andialbrecht/sqlparse": "Python", "BurntSushi/toml": "Go",
        "tox-dev/platformdirs": "Python", "arrow-py/arrow": "Python",
        "pypa/packaging": "Python", "python-poetry/tomlkit": "Python", "go-chi/chi": "Go",
        "google/go-cmp": "Go", "astanin/python-tabulate": "Python",
        "mahmoud/boltons": "Python"}
L2 = [r for r in SCOUT_RANKED if r != "spf13/pflag" and r not in C1]
assert all(r.split("/")[0].lower() not in ("pallets", "spf13") for r in L2)
l2 = sorted(L2, key=lambda r: (h("crb.w5.repo|20261113|" + r), r))
for i, r in enumerate(l2, 1):
    print(f"L2 {i:2d} {r:26s} {LANG[r]:6s} {h('crb.w5.repo|20261113|' + r)}")
print("sha256(L2 list in hash order, one owner/name a line, newline-ended) =",
      h("".join(r + "\n" for r in l2)))
print("L2 size", len(l2), "; C1 size", len(c1), "; names to qualify", len(l2) + len(c1))

# ---------------------------------------------------------------- 2. exact p facts
section("2. p_min and the exact sign test")
for n in (5, 6, 7, 8, 9, 10):
    print(f"n={n:2d} 2^n={2**n:5d} p_min=2/2^n={2 / 2**n:.7f}"
          f"  one dissenter (sign test)={2 * (1 + n) / 2**n:.5f}"
          f"  reachable at 0.05:{2 / 2**n < 0.05}  at 0.025:{2 / 2**n < 0.025}")


def sign_test_power(n, q, alpha):
    # two-sided exact sign test: reject when k agreeing units has p<alpha
    def p_of(k):
        tail = sum(math.comb(n, j) for j in range(k, n + 1)) / 2**n
        return min(1.0, 2 * tail)
    kmin = next((k for k in range(n // 2 + 1, n + 1) if p_of(k) < alpha), None)
    if kmin is None:
        return 0.0
    return sum(math.comb(n, k) * q**k * (1 - q)**(n - k) for k in range(kmin, n + 1))


q_w4 = 11 / 12
for n in (6, 7, 8, 9, 10):
    print(f"sign test power q=11/12 n={n}: alpha .05 {sign_test_power(n, q_w4, .05):.3f}"
          f"  alpha .025 {sign_test_power(n, q_w4, .025):.3f}")
print(f"(11/12)^6={q_w4**6:.4f} (11/12)^8={q_w4**8:.4f} "
      f"(11/12)^10+10(11/12)^9(1/12)={q_w4**10 + 10 * q_w4**9 / 12:.4f}")


# ---------------------------------------------------------------- 3. sign-flip helpers
def signflip_p(xs):
    sums = [0.0]
    for x in xs:
        sums = [s + x for s in sums] + [s - x for s in sums]
    obs = abs(sum(xs))
    return sum(1 for s in sums if abs(s) >= obs - 1e-12) / len(sums)


# t quantile from a regularised incomplete beta (Numerical Recipes betacf)
def _betacf(a, b, x):
    qab, qap, qam = a + b, a + 1, a - 1
    c, d = 1.0, 1 - qab * x / qap
    d = 1 / (d if abs(d) > 1e-300 else 1e-300)
    hh = d
    for m in range(1, 300):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1 + aa * d
        d = 1 / (d if abs(d) > 1e-300 else 1e-300)
        c = 1 + aa / c
        c = c if abs(c) > 1e-300 else 1e-300
        hh *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1 + aa * d
        d = 1 / (d if abs(d) > 1e-300 else 1e-300)
        c = 1 + aa / c
        c = c if abs(c) > 1e-300 else 1e-300
        de = d * c
        hh *= de
        if abs(de - 1) < 1e-14:
            break
    return hh


def betai(a, b, x):
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    bt = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
                  + a * math.log(x) + b * math.log(1 - x))
    if x < (a + 1) / (a + b + 2):
        return bt * _betacf(a, b, x) / a
    return 1 - bt * _betacf(b, a, 1 - x) / b


def t_cdf(t, df):
    x = df / (df + t * t)
    p = 0.5 * betai(df / 2, 0.5, x)
    return 1 - p if t > 0 else p


def t_q(prob, df):
    lo, hi = -50.0, 50.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if t_cdf(mid, df) < prob:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


section("3. t quantiles used by the intervals")
for df in (5, 6, 7, 8, 9, 11):
    print(f"df={df:2d} t(0.95)={t_q(.95, df):.4f} t(0.975)={t_q(.975, df):.4f}")
print("check: t(0.975,11) should be 2.2010 ->", round(t_q(.975, 11), 4))


def within_ok(xs, J):
    n = len(xs)
    mean = sum(xs) / n
    sd = math.sqrt(sum((x - mean) ** 2 for x in xs) / (n - 1))
    half = t_q(1 - 0.05 / J, n - 1) * sd / math.sqrt(n)
    return (mean - half > -0.15) and (mean + half < 0.15)


# ---------------------------------------------------------------- 4. normal-model power
section("4. Sign-flip power, unit difference ~ Normal(z,1), z = Phi^-1(q); 3000 waves")
rng = random.Random(SEED)
print("q      " + "  ".join(f"n={n}:a.05/a.025" for n in (6, 7, 8, 9, 10)))
for q in (0.99, 11 / 12, 0.85, 0.80, 0.75):
    z = N01.inv_cdf(q)
    row = []
    for n in (6, 7, 8, 9, 10):
        r05 = r025 = 0
        for _ in range(3000):
            xs = [rng.gauss(z, 1) for _ in range(n)]
            p = signflip_p(xs)
            if sum(xs) > 0:
                r05 += p < 0.05
                r025 += p < 0.025
        row.append(f"{r05 / 3000:.2f}/{r025 / 3000:.2f}")
    print(f"{q:.3f}  " + "  ".join(f"{c:>13s}" for c in row))

section("5. q per repository from effect, tau, s_c, m: q = Phi(effect / sqrt(tau^2+s_c^2/m))")
for s_c in (45, 60):
    for tau in (10, 15, 20):
        cells = []
        for eff in (15, 25, 30, 46):
            cells.append(" ".join(f"m{m}:{N01.cdf(eff / math.sqrt(tau**2 + s_c**2 / m)):.3f}"
                                  for m in (5, 6, 10, 20)))
        print(f"s_c={s_c} tau={tau}: " + " | ".join(
            f"eff{e}[{c}]" for e, c in zip((15, 25, 30, 46), cells)))
print("worked: sqrt(15^2+45^2/20)=", round(math.sqrt(225 + 2025 / 20), 2),
      " sqrt(15^2+60^2/6)=", round(math.sqrt(225 + 3600 / 6), 2),
      " sqrt(15^2+60^2/10)=", round(math.sqrt(225 + 360), 2))


# ---------------------------------------------------------------- 6. discrete design sim
def draw_repo(rng, m, mu0, delta, tau_e, rho=0.25, sd_mu=0.15):
    mu = min(0.95, max(0.05, rng.gauss(mu0, sd_mu)))
    k = 1 / rho - 1
    d_r = rng.gauss(delta, tau_e)
    diffs = []
    truth = []
    for _ in range(m):
        p = rng.betavariate(mu * k, (1 - mu) * k)
        pl = min(1.0, max(0.0, p + d_r))
        a = (rng.random() < p) + (rng.random() < p)
        b = (rng.random() < pl) + (rng.random() < pl)
        diffs.append((b - a) / 2)
        truth.append(pl - p)
    return sum(diffs) / m, sum(truth) / m


def design_sim(n, m, mu0, delta, tau_e, waves, rng):
    dec05 = dec025 = w1 = w2 = wrong = zeros_lt6 = 0
    real = 0.0
    for _ in range(waves):
        reps = [draw_repo(rng, m, mu0, delta, tau_e) for _ in range(n)]
        xs = [r[0] for r in reps]
        real += sum(r[1] for r in reps) / n
        p = signflip_p(xs)
        s = sum(xs)
        right = (s < 0) if delta < 0 else (s > 0)
        nz = sum(1 for x in xs if abs(x) > 1e-12)
        zeros_lt6 += nz < 6
        if delta != 0:
            dec05 += (p < 0.05) and right
            dec025 += (p < 0.025) and right
            wrong += (p < 0.05) and not right
        else:
            dec05 += p < 0.05
            dec025 += p < 0.025
            if p >= 0.05 and nz >= 6:
                w1 += within_ok(xs, 1)
            if p >= 0.025 and nz >= 6:
                w2 += within_ok(xs, 2)
    return (dec05 / waves, dec025 / waves, w1 / waves, w2 / waves, wrong / waves,
            zeros_lt6 / waves, 100 * real / waves)


section("6. Discrete simulation of the registered read (repository unit, exact sign-flip)")
print("model: repo A0 mean ~ N(mu0,0.15) clipped [.05,.95]; commit chance Beta, ICC 0.25;")
print("lever shift per repo ~ N(delta, tau_e); lever chance clipped [0,1]; 2 attempts/arm;")
print("1,500 waves a cell; seed 20261113. cols: P(correct Better/Worse) a.05 | a.025 |")
print("P(Within15 | J=1) | P(Within15 | J=2) | P(wrong-sign decisive) | P(<6 nonzero) | realised")
rng = random.Random(SEED + 1)
for m in (6, 10):
    for tau_e in (0.10, 0.20):
        for mu0 in (0.7,):
            for delta in (0.0, -0.15, -0.25, -0.30, -0.46):
                for n in (6, 7, 8, 10):
                    r = design_sim(n, m, mu0, delta, tau_e, 1500, rng)
                    print(f"m={m:2d} tau_e={tau_e:.2f} mu0={mu0} delta={delta:+.2f} n={n:2d}: "
                          f"{r[0]:.3f} | {r[1]:.3f} | {r[2]:.3f} | {r[3]:.3f} | {r[4]:.3f} | "
                          f"{r[5]:.3f} | real {r[6]:+.1f}")

# ---------------------------------------------------------------- 7. W selection
section("7. W pilot rule: P(pilot gap >= 30 points), pilot of P commits x 2 attempts per arm")
rng = random.Random(SEED + 2)
for P in (10,):
    for gap in (0.10, 0.15, 0.20, 0.30, 0.45):
        hit = 0
        T = 20000
        for _ in range(T):
            a = b = 0
            for _c in range(P):
                p = rng.betavariate(0.7 * 3, 0.3 * 3)
                pw = max(0.0, p - gap)
                a += (rng.random() < p) + (rng.random() < p)
                b += (rng.random() < pw) + (rng.random() < pw)
            hit += (a - b) / (2 * P) >= 0.30
        print(f"P={P} true gap {gap * 100:.0f} points: P(selected) = {hit / T:.3f}")

# ---------------------------------------------------------------- 8. known-answer sets
section("8. Synthetic known-answer sets for the read script (expected outputs)")
K = {
    "K1 eight repos all -0.5": [-0.5] * 8,
    "K2 eight repos +-0.1 alternating": [0.1, -0.1] * 4,
    "K3 six repos, one zero, five -0.4": [0.0] + [-0.4] * 5,
    "K4 seven repos all +0.3": [0.3] * 7,
    "K5 ten repos, nine -0.2 one +0.1": [-0.2] * 9 + [0.1],
}
for name, xs in K.items():
    n = len(xs)
    mean = sum(xs) / n
    sd = math.sqrt(sum((x - mean) ** 2 for x in xs) / (n - 1)) if n > 1 else 0
    p = signflip_p(xs)
    nz = sum(1 for x in xs if x != 0)
    half90 = t_q(.95, n - 1) * sd / math.sqrt(n)
    print(f"{name}: D={100 * mean:+.4f} p={p:.7f} ({round(p * 2**n)}/{2**n}) nonzero={nz} "
          f"90% half-width={100 * half90:.4f} points")

# ---------------------------------------------------------------- 9. costs
section("9. Costs, product dollars, unconfirmed")
spent_all, run_rows = 48.115522, 42.575859
r = spent_all / 120
print(f"rate all-in per commit-arm = 48.115522/120 = {r:.6f}; wave rows only = "
      f"{run_rows / 120:.6f}")
HIGHX = 2.5
LEFT = 200 - 69.98
print(f"money left on the line = 200 - 69.98 = {LEFT:.2f}")
author = 0.174468
print(f"Wave 4 authoring (Cerebras) = {author}; per S1 attempt over 126 attempts = "
      f"{author / 126:.6f}")


def design(name, n, m, arms, pilot_ca):
    wave_ca = n * m * arms
    tot_ca = wave_ca + pilot_ca
    c = tot_ca * r
    hi = c * HIGHX
    line = math.ceil(hi)
    lift = max(0.0, line - LEFT)
    per_repo_hi = m * arms * r * HIGHX
    k_at_left = math.floor((LEFT - pilot_ca * r * HIGHX) / per_repo_hi)
    s1_att = 2 * (n * m + pilot_ca // arms)
    print(f"{name}: n={n} m={m} arms={arms} wave commit-arms={wave_ca} pilot={pilot_ca} "
          f"total={tot_ca}; central={c:.2f} high={hi:.2f} line={line} lift={lift:.2f}; "
          f"high per repo={per_repo_hi:.2f}; whole repos inside $130.02 at high={k_at_left}; "
          f"S1 attempts={s1_att}, author $ central={s1_att * author / 126:.2f}")


design("D1 two arms m=10 n=10", 10, 10, 2, 4 * 2)
design("D1 two arms m=10 n=7 ", 7, 10, 2, 4 * 2)
design("D1 two arms m=20 n=10", 10, 20, 2, 4 * 2)
design("D2 three arms m=10 n=10 (pilot 10 commits x A0,S1,2 W)", 10, 10, 3, 10 * 4)
design("D2 three arms m=10 n=7 (pilot 7 commits x 4)", 7, 10, 3, 7 * 4)
design("D3 two arms m=6 n=10", 10, 6, 2, 4 * 2)
design("D3 two arms m=6 n=7 ", 7, 6, 2, 4 * 2)
design("D3 two arms m=4 n=10 (rejected: q below 11/12)", 10, 4, 2, 4 * 2)

section("10. Run time, from Wave 4: 49 runs x 5 commits in 10.06 h")
per_ca = 10.06 * 60 / (49 * 5)
print(f"minutes per commit-attempt-run slot = {per_ca:.3f}")
for name, ca in (("D1 n10", 208), ("D2 n10", 340), ("D3 n10", 128)):
    print(f"{name}: {ca} commit-arms x 2 attempts x {per_ca:.3f} min = "
          f"{ca * 2 * per_ca / 60:.1f} h")
