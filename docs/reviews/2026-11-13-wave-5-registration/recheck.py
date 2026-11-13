"""Independent recheck of Wave 5 registration v3 numbers. Standard library only.

Run from this folder: ``python3 -I recheck.py > recheck.out.txt``. Part 4 uses seed 777 and
part 6 seed 4242.

Navigation
----------
What it is:   The forking-path check's independent recomputation of the Wave 5
              registration's version 3 figures — written apart from w5v3_calc.py, with no
              builder, no model and no product code.
What it does: Recomputes the list hashes and run order, the costs, the p floors and exact
              power, the simulated power, the known-answer sets and the discrete simulation of
              the read, each part headed by its claim tag, its method and its sample size or
              seed. It spends nothing and writes nothing.
How:          ``h`` hashes the lists → exact sign-test arithmetic → ``flip_p`` enumerates
              every sign pattern for seeded waves → ``word`` applies the word rule to K1 to K7
              → ``sim`` draws seeded waves of the registered read.
Layer:        tests — docs/ARCHITECTURE.md#7-cross-cutting-concepts
ADRs:         none
Works with:   docs/reviews/2026-11-13-wave-5-registration.md (appendix A records its sha256
              and section 7.4 quotes its method B figures),
              docs/reviews/2026-11-13-wave-5-registration/recheck.out.txt (its recorded
              output), docs/reviews/2026-11-13-wave-5-registration/w5v3_calc.py (the script
              it checks)
Tested by:    untested — a one-off check; its output is committed beside it and is
              reproduced exactly by the command above
Touch when:   never for a new repository; it is the record of a registration, and a new
              check is a new file beside a new review.
"""

import hashlib
import itertools
import math
import random
import statistics
from math import comb
from statistics import NormalDist

SIM = "simulation under stated assumptions, not a measurement of the product"
EX = "exact arithmetic on stated inputs, no sample; not a measurement of the product"


def h(s):
    return hashlib.sha256(s.encode()).hexdigest()


print("== 1 lists")
print("[hypothesis — design input: sha256 over the 12 C1 and 11 L2 names; " + EX + "]")
c1 = [
    "gorilla/mux",
    "jpadilla/pyjwt",
    "rs/zerolog",
    "hynek/structlog",
    "pelletier/go-toml",
    "jd/tenacity",
    "sirupsen/logrus",
    "tox-dev/filelock",
    "marshmallow-code/marshmallow",
    "hashicorp/go-version",
    "urfave/cli",
    "more-itertools/more-itertools",
]
print("C2 order ok:", sorted(c1, key=lambda x: (h("crb.d3.repo|20261112|" + x), x)) == c1)
print("sha C1:", h("".join(x + "\n" for x in c1)))
l2 = [
    "labstack/echo",
    "mahmoud/boltons",
    "BurntSushi/toml",
    "python-poetry/tomlkit",
    "astanin/python-tabulate",
    "arrow-py/arrow",
    "andialbrecht/sqlparse",
    "pypa/packaging",
    "tox-dev/platformdirs",
    "go-chi/chi",
    "google/go-cmp",
]
print("L2 order ok:", sorted(l2, key=lambda x: (h("crb.w5.repo|20261113|" + x), x)) == l2)
print("sha L2:", h("".join(x + "\n" for x in l2)))
print("run order of C1 names (crb.w5.run):")
for x in sorted(c1 + l2, key=lambda x: h("crb.w5.run|20261113|" + x)):
    print("  ", x, "C1" if x in c1 else "L2")

print("== 2 costs")
print(
    "[hypothesis — cost and time projection from Wave 4's rate over 120 commit-arms; unconfirmed]"
)
r = 48.115522 / 120
print("rate", round(r, 6))
for n in range(6, 13):
    ca = n * 12 + 8
    hi = ca * r * 2.5
    print(
        n,
        ca,
        round(ca * r, 2),
        round(hi, 2),
        math.ceil(hi),
        round(max(0, math.ceil(hi) - 130.02), 2),
        round(hi - 130.02, 2),
    )
print("repo high", round(12 * r * 2.5, 4), "pilot high", round(8 * r * 2.5, 4))
print(
    "D1 n10",
    208,
    round(208 * r, 2),
    round(208 * r * 2.5, 2),
    "D1 n7",
    148,
    round(148 * r, 2),
    round(148 * r * 2.5, 2),
)
print(
    "D2 n10",
    340,
    round(340 * r, 2),
    round(340 * r * 2.5, 2),
    "D2 n7",
    250,
    round(250 * r, 2),
    round(250 * r * 2.5, 2),
)
print(
    "author n10 central",
    round((10 * 6 + 4) * 2 * 0.174468 / 126, 3),
    "D2 S1",
    (100 + 10) * 2,
    round(220 * 0.174468 / 126, 3),
)
print("hours n10", round(128 * 2 * 2.464 / 60, 2), "n6", round(80 * 2 * 2.464 / 60, 2))

print("== 3 p floors and method A")
print("[hypothesis — exact sign test and binomial power at q = 11/12, n = 5..12; " + EX + "]")
for n in [5, 6, 7, 8, 9, 10, 11, 12]:
    print(n, 2 / 2**n)
q = 11 / 12


def sign_p(k, n):  # two-sided exact sign test, k agree of n, equal magnitudes
    tail = sum(comb(n, i) for i in range(k, n + 1))
    return min(1.0, 2 * tail / 2**n)


for n in range(6, 13):
    ks = [k for k in range(n + 1) if k > n / 2 and sign_p(k, n) < 0.05]
    kmin = min(ks)
    pw = sum(comb(n, k) * q**k * (1 - q) ** (n - k) for k in range(kmin, n + 1))
    print(f"n={n} needs {kmin}/{n} power {pw:.4f}")

print("== 4 method B: sign-flip, D_r~N(z,1), my seed")
print(
    "[hypothesis — 3,000 simulated waves a cell for n = 6..10 and 1,500 for n = 11, 12, seed 777; "
    + SIM
    + "]"
)
z = NormalDist().inv_cdf(q)
print("z", round(z, 4))


def flip_p(d):
    n = len(d)
    obs = abs(sum(d))
    c = 0
    for s in itertools.product((1, -1), repeat=n):
        if abs(sum(a * b for a, b in zip(s, d, strict=True))) >= obs - 1e-12:
            c += 1
    return c / 2**n


rng = random.Random(777)  # noqa: S311 - a seeded simulation, not cryptography
for n in range(6, 13):
    W = 3000 if n <= 10 else 1500
    hit = 0
    for _ in range(W):
        d = [rng.gauss(z, 1) for _ in range(n)]
        if sum(d) > 0 and flip_p(d) < 0.05:
            hit += 1
    pw = hit / W
    print(f"n={n} B {pw:.3f} se {math.sqrt(pw * (1 - pw) / W):.3f}")


# t quantiles 0.95 for df 5..11 by bisection on a numeric t cdf
def tcdf(x, df):
    # Simpson integration of t pdf from 0 to x
    c = math.gamma((df + 1) / 2) / (math.sqrt(df * math.pi) * math.gamma(df / 2))

    def f(t):
        return c * (1 + t * t / df) ** (-(df + 1) / 2)

    steps = 2000
    hstep = x / steps
    s = f(0) + f(x)
    for i in range(1, steps):
        s += (4 if i % 2 else 2) * f(i * hstep)
    return 0.5 + s * hstep / 3


TQ = {}
for df in range(5, 12):
    lo, hi = 0.5, 5
    for _ in range(60):
        mid = (lo + hi) / 2
        if tcdf(mid, df) < 0.95:
            lo = mid
        else:
            hi = mid
    TQ[df] = lo
print("== 5 K sets")
print("[hypothesis — seven synthetic sets, exact sign-flip and t; " + EX + "]")
T = {5: 2.015048, 7: 1.894579, 9: 1.833113}


def word(d, usable=1.0):
    n = len(d)
    mean_d = sum(d) / n
    p = flip_p(d)
    nz = sum(1 for x in d if x != 0)
    hw = TQ[n - 1] * statistics.stdev(d) / math.sqrt(n)
    if p < 0.05 and mean_d > 0:
        w = "Better"
    elif p < 0.05 and mean_d < 0:
        w = "Worse"
    elif mean_d - hw > -15 and mean_d + hw < 15 and nz >= 6 and usable >= 0.9:
        w = "Within 15"
    else:
        w = "Undecided"
    return round(mean_d, 4), p, nz, round(hw, 4), w


K7 = [100 * (1 - 3) / 4] + [100 * (5 - 9) / 12] * 5
for name, d, u in [
    ("K1", [-50] * 8, 1),
    ("K2", [10, -10] * 4, 1),
    ("K3", [0] + [-40] * 5, 1),
    ("K4", [30] * 7, 1),
    ("K5", [-20] * 9 + [10], 1),
    ("K6", [10, -10] * 4, 0.85),
    ("K7", K7, 1),
]:
    print(name, word(d, u))

print("== 6 discrete sim, my implementation")
print(
    "[hypothesis — 600 simulated waves a cell for n = 6..8, 400 for n = 10 and 800 a thin-repository cell, one stream, seed 4242; "
    + SIM
    + "]"
)


def sim(n, delta, tau, waves, rng, *, m=6, thin=0):
    res = {"dec": 0, "w15": 0, "und": 0, "und_lt6": 0, "wrong": 0}
    for _ in range(waves):
        d = []
        for j in range(n):
            mr = 2 if j < thin else m
            mu = min(0.95, max(0.05, rng.gauss(0.7, 0.15)))
            sh = rng.gauss(delta, tau)
            a = mu * 3
            b = (1 - mu) * 3
            ca = cs = 0
            for _c in range(mr):
                pc = rng.betavariate(a, b)
                ps = min(1, max(0, pc + sh))
                ca += sum(rng.random() < pc for _ in range(2))
                cs += sum(rng.random() < ps for _ in range(2))
            d.append(100 * (cs - ca) / (2 * mr))
        mean_d = sum(d) / n
        p = flip_p(d)
        nz = sum(1 for x in d if x != 0)
        hw = TQ[n - 1] * statistics.stdev(d) / math.sqrt(n)
        if p < 0.05:
            if delta == 0 or (mean_d < 0) == (delta < 0):
                res["dec" if delta != 0 else "wrong"] += 1
            else:
                res["wrong"] += 1
        elif mean_d - hw > -15 and mean_d + hw < 15 and nz >= 6:
            res["w15"] += 1
        else:
            res["und"] += 1
            if nz < 6:
                res["und_lt6"] += 1
    return {k: round(v / waves, 3) for k, v in res.items()}


print("t0.95", {k: round(v, 4) for k, v in TQ.items()})
rng = random.Random(4242)  # noqa: S311 - a seeded simulation, not cryptography
for tau in (0.10, 0.20):
    for delta in (0.0, -0.25, -0.46):
        for n in (6, 7, 8, 10):
            print(f"tau={tau} delta={delta} n={n}", sim(n, delta, tau, 600 if n <= 8 else 400, rng))
print("thin repo, n=7, tau .10")
for delta in (0.0, -0.46):
    for thin in (0, 1):
        print(delta, thin, sim(7, delta, 0.10, 800, rng, thin=thin))
