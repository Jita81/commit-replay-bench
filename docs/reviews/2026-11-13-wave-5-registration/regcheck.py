"""Independent recomputation for wave5-registration-v2 (stdlib only)."""
import hashlib, itertools, math, random, statistics
from statistics import NormalDist

N = NormalDist()
h = lambda s: hashlib.sha256(s.encode()).hexdigest()

print("== 1. lists")
C1 = ["gorilla/mux","jpadilla/pyjwt","rs/zerolog","hynek/structlog","pelletier/go-toml","jd/tenacity",
      "sirupsen/logrus","tox-dev/filelock","marshmallow-code/marshmallow","hashicorp/go-version",
      "urfave/cli","more-itertools/more-itertools"]
c2 = sorted(C1, key=lambda r: (h("crb.d3.repo|20261112|"+r), r))
print("C2 order same as registered:", c2 == C1)
print("sha256 C1 list", h("".join(r+"\n" for r in c2)))
scout = ["urfave/cli","labstack/echo","andialbrecht/sqlparse","BurntSushi/toml","tox-dev/platformdirs",
         "arrow-py/arrow","spf13/pflag","pypa/packaging","python-poetry/tomlkit","pelletier/go-toml",
         "more-itertools/more-itertools","go-chi/chi","google/go-cmp","astanin/python-tabulate",
         "mahmoud/boltons","sirupsen/logrus"]
L2 = [r for r in scout if r != "spf13/pflag" and r not in C1]
L2 = sorted(L2, key=lambda r: (h("crb.w5.repo|20261113|"+r), r))
for i, r in enumerate(L2, 1):
    print(f"L2 {i:2d} {r:26s} {h('crb.w5.repo|20261113|'+r)}")
print("sha256 L2 list", h("".join(r+"\n" for r in L2)))

print("== 2. p floors, Holm")
for n in (5,6,7,8,9,10):
    print(n, 2/2**n, "ok.05", 2/2**n < .05, "ok.025", 2/2**n < .025)
print("Holm J=2 thresholds: 0.025 then 0.05; J=1: 0.05")

def signflip_p(d):
    obs = abs(sum(d)); c = 0
    for s in itertools.product((1,-1), repeat=len(d)):
        if abs(sum(a*b for a,b in zip(s,d))) >= obs - 1e-9: c += 1
    return c, 2**len(d)

def tq(p, df):  # t quantile by bisection on stdlib-free CDF (numerical integration)
    def cdf(x):
        # Simpson integration of t pdf from 0 to x
        c = math.gamma((df+1)/2)/(math.sqrt(df*math.pi)*math.gamma(df/2))
        f = lambda t: c*(1+t*t/df)**(-(df+1)/2)
        k = 2000; hh = x/k
        s = f(0)+f(x)+sum((4 if i%2 else 2)*f(i*hh) for i in range(1,k))
        return .5 + s*hh/3
    lo, hi = 0., 20.
    for _ in range(80):
        mid = (lo+hi)/2
        if cdf(mid) < p: lo = mid
        else: hi = mid
    return (lo+hi)/2

print("== 3. t quantiles")
for df in (5,6,7,8,9,11):
    print(df, round(tq(.95,df),4), round(tq(.975,df),4))

print("== 4. K sets")
K = {"K1":[-50]*8, "K2":[10,-10]*4, "K3":[0]+[-40]*5, "K4":[30]*7, "K5":[-20]*9+[10]}
for k, d in K.items():
    c, tot = signflip_p(d); m = statistics.mean(d)
    hw = tq(.95,len(d)-1)*statistics.stdev(d)/math.sqrt(len(d)) if len(set(d))>1 else 0.0
    nz = sum(1 for x in d if x)
    if c/tot < .05: w = "Better" if m>0 else "Worse"
    elif abs(m)+hw < 15 and nz >= 6: w = "Within 15"
    else: w = "Undecided"
    print(k, round(m,4), f"{c}/{tot}={c/tot:.7f}", nz, round(hw,4), w)

print("== 5. sign-flip power, unit ~ N(z,1), z=Phi^-1(q)")
rnd = random.Random(7)
def crit(n, alpha):
    # exact sign-flip is data dependent; simulate it
    pass
def power(q, n, alpha, W=4000):
    z = N.inv_cdf(q); hit = 0
    pats = list(itertools.product((1,-1), repeat=n))
    for _ in range(W):
        d = [rnd.gauss(z,1) for _ in range(n)]
        obs = abs(sum(d))
        c = sum(1 for s in pats if abs(sum(a*b for a,b in zip(s,d))) >= obs-1e-12)
        if c/len(pats) < alpha and sum(d) > 0: hit += 1
    return hit/W
for n in (6,7,8,10):
    print("q=11/12 n", n, round(power(11/12,n,.05),3), round(power(11/12,n,.025),3))
print("q m=4", round(N.cdf(46/math.sqrt(15**2+60**2/4)),4), "m=6", round(N.cdf(46/math.sqrt(15**2+60**2/6)),4),
      "m=10", round(N.cdf(46/math.sqrt(15**2+60**2/10)),4), "m=20", round(N.cdf(46/math.sqrt(15**2+60**2/20)),4))
print("q m=2", round(N.cdf(46/math.sqrt(15**2+60**2/2)),4), "m=3", round(N.cdf(46/math.sqrt(15**2+60**2/3)),4))

print("== 6. W pilot rule, binomial 20 attempts per arm, A0 p=0.7")
from math import comb
def sel(gap, pa=0.7, n=20):
    pw = pa-gap; t = 0.
    for a in range(n+1):
        for w in range(n+1):
            if (a-w)/n*100 >= 30-1e-9:
                t += comb(n,a)*pa**a*(1-pa)**(n-a)*comb(n,w)*pw**w*(1-pw)**(n-w)
    return t
for g in (.10,.15,.20,.30,.45):
    print("gap", g, round(sel(g),3))

print("== 7. costs")
r = 48.115522/120; print("rate", r, "rows-only", None)
def cost(n,m,arms,pilot):
    tot = n*m*arms+pilot; c = tot*r; hi = c*2.5; line = math.ceil(hi)
    return tot, round(c,2), round(hi,2), line, round(max(0,line-130.02),2), round(tot*2*2.464/60,1)
for lab,args in [("D1 n10",(10,10,2,8)),("D1 n7",(7,10,2,8)),("D1 m20",(10,20,2,8)),
                 ("D2 n10",(10,10,3,40)),("D2 n7 pilot28",(7,10,3,28)),("D2 n7 pilot40",(7,10,3,40)),
                 ("D3 n10",(10,6,2,8)),("D3 n7",(7,6,2,8)),("m4 n10",(10,4,2,8)),("m4 n7",(7,4,2,8)),
                 ("m6 n6",(6,6,2,8))]:
    print(lab, cost(*args))
print("per repo high D3", round(12*r*2.5,2), "D1", round(20*r*2.5,2), "D2", round(30*r*2.5,2))
print("S1 attempts D2 n10 = (100+10)*2 =", 220, "author $", round(220*0.174468/126,3), "reg says 226")
print("D3 author $", round(128*0.174468/126,3), "minutes/slot", 10.06*60/245)
print("lift for D1 smallest at n=10", round(math.ceil(208*r*2.5)-130.02,2))
