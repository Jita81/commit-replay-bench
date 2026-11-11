"""Coverage of the Wave 4 registration's batch-level t interval (part 6, item 2).

Run from the repository root:
``uv run --no-project --with numpy python docs/reviews/2026-11-10-wave-4-registration/interval_sim.py``.
Prints, for each setting,
the true mean per-commit difference, the share of simulated waves whose 95% interval
missed it on either side, the share whose UPPER end fell below it, and that last share
again counting only waves in which at least ``MIN_NONZERO`` batches had a non-zero sum
(the registration's guard on the "no 15-point effect" call). That last share is a miss
rate of the guarded interval only: the primary and sensitivity tests of the call are not
applied here, so it is not an error rate for the call. Then the same for distributions
chosen to break the interval, and the half-width of the distribution-free bound.

Model of one wave: 18 batches laid out as the registration's four cells in batches of
five (24, 21, 16 and 20 commits). Each commit has a starting chance of a clean row (all
equal to ``mean``, or drawn from a beta distribution with that mean and intra-class
correlation ``rho``). Each batch has four runs (two per arm); each run shifts every
commit's chance by one normal draw with standard deviation ``sd``; ``S1`` adds ``eff``;
chances are clipped to [0, 1]. A commit's difference is its S1 rate minus its A0 rate
over the two attempts per arm.
"""

from math import log, sqrt

import numpy as np

SEED = 20261111
SIZES = np.array([5, 5, 5, 5, 4, 5, 5, 5, 5, 1, 5, 5, 5, 1, 5, 5, 5, 5])
B, N = len(SIZES), int(SIZES.sum())
T975 = 2.109816  # Student's t, 97.5% point, 17 degrees of freedom
REPS = 4000
MIN_NONZERO = 6  # the guard of part 6, item 4
rng = np.random.default_rng(SEED)


def interval(sums: np.ndarray) -> tuple[float, float]:
    d = sums.sum() / N
    se = sqrt(B / (B - 1) * ((sums - SIZES * d) ** 2).sum()) / N
    return d - T975 * se, d + T975 * se


def errors(draw, truth: float, reps: int = REPS) -> tuple[float, float, float]:
    miss = low = guarded = 0
    for _ in range(reps):
        sums = np.array([draw(int(n)).sum() for n in SIZES])
        lo, hi = interval(sums)
        miss += not (lo <= truth <= hi)
        low += hi < truth
        guarded += hi < truth and int((sums != 0).sum()) >= MIN_NONZERO
    return miss / reps, low / reps, guarded / reps


def realistic(mean: float, rho: float, eff: float, sd: float):
    def draw(n: int) -> np.ndarray:
        if rho > 0:
            k = (1 - rho) / rho
            p = rng.beta(mean * k, (1 - mean) * k, n)
        else:
            p = np.full(n, mean)
        shock = rng.normal(0, sd, 4) if sd > 0 else np.zeros(4)
        a0 = sum(rng.random(n) < np.clip(p + shock[i], 0, 1) for i in (0, 1)) / 2
        s1 = sum(rng.random(n) < np.clip(p + eff + shock[i], 0, 1) for i in (2, 3)) / 2
        return s1 - a0

    return draw


def main() -> None:
    print("mean rho eff sd | truth | missed either side | upper end below truth | same, guarded")
    worst_miss = worst_low = worst_guarded = 0.0
    for mean in (0.3, 0.5, 0.7, 0.9):
        for rho in (0.0, 0.25, 0.5):
            for eff in (0.0, 0.15, 0.30):
                for sd in (0.0, 0.05, 0.10):
                    draw = realistic(mean, rho, eff, sd)
                    truth = float(np.concatenate([draw(5) for _ in range(40000)]).mean())
                    miss, low, guarded = errors(draw, truth)
                    worst_miss, worst_low = max(worst_miss, miss), max(worst_low, low)
                    worst_guarded = max(worst_guarded, guarded)
                    print(
                        f"{mean} {rho} {eff} {sd} | {truth:.3f} | {miss:.3f} | {low:.3f} | {guarded:.3f}"
                    )
    print(
        f"worst over the grid: missed {worst_miss:.3f}, upper end below truth {worst_low:.3f}, "
        f"guarded {worst_guarded:.3f}"
    )

    # distributions chosen to break it: a rare effect that lands on a whole batch at once
    for q in (0.85, 0.70):
        truth = 1 - q
        miss, low, guarded = errors(
            lambda n, q=q: np.full(n, 0.0 if rng.random() < q else 1.0), truth
        )
        print(
            f"whole batch 0 with chance {q}, else +1 | {truth:.2f} | {miss:.3f} | {low:.3f} | {guarded:.3f}"
        )
    # the reviewer's example: a whole batch is 0 with chance 0.9, else +0.5
    miss, low, guarded = errors(lambda n: np.full(n, 0.0 if rng.random() < 0.9 else 0.5), 0.05)
    print(
        f"whole batch 0 with chance 0.9, else +0.5 | 0.05 | {miss:.3f} | {low:.3f} | {guarded:.3f}"
    )
    # the same rare effect landing on single commits
    miss, low, guarded = errors(lambda n: (rng.random(n) >= 0.85).astype(float), 0.15)
    print(
        f"each commit 0 with chance 0.85, else +1 | 0.15 | {miss:.3f} | {low:.3f} | {guarded:.3f}"
    )

    # distribution-free bound (Hoeffding): batch sums independent, each within +-n_b
    half = sqrt(2 * log(2 / 0.05) * float((SIZES**2).sum())) / N
    print(f"distribution-free 95% half-width: {half:.3f}")


if __name__ == "__main__":
    main()
