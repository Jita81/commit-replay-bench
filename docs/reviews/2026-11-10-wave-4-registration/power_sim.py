"""Power of the Wave 4 primary test on the cut lists of Amendment 2.

Run from the repository root:
``uv run --no-project --with numpy python docs/reviews/2026-11-10-wave-4-registration/power_sim.py``.
Prints, for each setting, the share of simulated waves in which the registered primary test
(part 6, item 1: the exact two-sided sign-flip test at 0.05 that flips whole batches)
rejected, for an added chance of 0, 15, 20 and 25 points, and beside it the realised effect
at each non-zero added chance.

The added chance is what ``S1`` adds to a commit's chance before clipping; it labels each
column and is not the true effect. Clipping to [0, 1] can only shrink it, so the realised
effect (the mean over the simulated commits, under each of the batch's four shocks, of the
clipped chance with the added chance minus the clipped chance without it) is at or below its
label. It is computed from the chances and shocks already drawn and takes no random draw, so
every rejection share is the one first recorded.

Model of one wave: the cut lists of Amendment 2, four cells of 15 commits in batches of
five, so 12 batches and 60 commits. Each commit has a starting chance of a clean row drawn
from a beta distribution with mean ``mean`` and intra-class correlation ``rho`` (all equal
to ``mean`` when ``rho`` is 0). Each batch has four runs (two per arm); each run shifts
every commit's chance by one normal draw with standard deviation ``sd``; ``S1`` adds
``eff`` (the added chance); chances are clipped to [0, 1]. A commit's difference is its S1
rate minus its A0 rate over the two attempts per arm. The grid of means, correlations and
shocks is the one decision R-1's revised simulation used.

Navigation
----------
What it is:   The Wave 4 registration's rerun of its power simulation on the cut lists — a
              model of the wave's layout, with no builder, no model and no product code.
What it does: Simulates waves under a grid of settings and prints how often the batch
              sign-flip test rejected at each added chance, and the realised effect after
              clipping. It spends nothing and writes nothing.
How:          ``batch_sums`` draws every wave's batch sums with a fixed seed → ``rejects``
              (the exact test over all 4,096 sign patterns) → one printed line per setting
              and the range over the grid.
Layer:        tests — docs/ARCHITECTURE.md#7-cross-cutting-concepts
ADRs:         none
Works with:   docs/reviews/2026-11-10-wave-4-registration.md (Amendment 2 cites its
              figures), docs/reviews/2026-11-10-wave-4-registration/power_sim.out.txt (its
              recorded output),
              docs/reviews/2026-11-10-wave-4-registration/interval_sim.py (the same model
              of a batch, for the interval)
Tested by:    untested — a one-off simulation; its output is committed beside it and is
              reproduced exactly by the command above
Touch when:   never for a new repository; it is the record of a registration, and a new
              simulation is a new file beside a new review.
"""

from itertools import product

import numpy as np

SEED = 20261112
SIZES = np.full(12, 5)  # 4 cells x 15 commits, batches of five
B = len(SIZES)
REPS = 2000
ALPHA = 0.05
EFFECTS = (0.0, 0.15, 0.20, 0.25)
SIGNS = np.array(list(product((1.0, -1.0), repeat=B)))  # every one of the 2^B sign patterns
rng = np.random.default_rng(SEED)


def batch_sums(
    mean: float, rho: float, eff: float, sd: float, reps: int = REPS
) -> tuple[np.ndarray, float]:
    """Each simulated wave's batch sums of per-commit differences, shape (reps, B), and the
    realised effect: the mean over every commit and each of its batch's four shocks of
    ``clip(p + eff + shock) - clip(p + shock)``. The realised effect takes no random draw."""
    n = int(SIZES[0])
    shape = (reps, B, n)
    if rho > 0:
        k = (1 - rho) / rho
        p = rng.beta(mean * k, (1 - mean) * k, shape)
    else:
        p = np.full(shape, mean)
    shock = rng.normal(0, sd, (reps, B, 4, 1)) if sd > 0 else np.zeros((reps, B, 4, 1))
    a0 = sum(rng.random(shape) < np.clip(p + shock[:, :, i], 0, 1) for i in (0, 1)) / 2
    s1 = sum(rng.random(shape) < np.clip(p + eff + shock[:, :, i], 0, 1) for i in (2, 3)) / 2
    realised = np.mean(
        [
            np.clip(p + eff + shock[:, :, i], 0, 1) - np.clip(p + shock[:, :, i], 0, 1)
            for i in range(4)
        ]
    )
    return (s1 - a0).sum(axis=2), float(realised)


def rejects(sums: np.ndarray) -> float:
    """Share of waves whose exact two-sided batch sign-flip p-value is below ``ALPHA``."""
    observed = np.abs(sums.sum(axis=1))
    flipped = np.abs(sums @ SIGNS.T)  # (reps, 2^B): the summed difference under each pattern
    p = (flipped >= observed[:, None] - 1e-9).mean(axis=1)
    return float((p < ALPHA).mean())


def main() -> None:
    """Print the grid and the range of each column over it."""
    print(
        f"[hypothesis] simulated by power_sim.py, seed {SEED}, {REPS} waves a setting, "
        f"{B} batches of 5 ({int(SIZES.sum())} commits); a simulation, not a measurement of the product"
    )
    print(
        "mean rho sd | rejected at added chance "
        + " ".join(f"{e:.2f}" for e in EFFECTS)
        + " | realised effect at added chance "
        + " ".join(f"{e:.2f}" for e in EFFECTS[1:])
    )
    lo = dict.fromkeys(EFFECTS, 1.0)
    hi = dict.fromkeys(EFFECTS, 0.0)
    rlo = dict.fromkeys(EFFECTS, 1.0)
    rhi = dict.fromkeys(EFFECTS, 0.0)
    for mean in (0.3, 0.5, 0.7):
        for rho in (0.0, 0.25, 0.5):
            for sd in (0.0, 0.05, 0.10):
                shares, realised = [], []
                for eff in EFFECTS:
                    sums, real = batch_sums(mean, rho, eff, sd)
                    share = rejects(sums)
                    lo[eff], hi[eff] = min(lo[eff], share), max(hi[eff], share)
                    rlo[eff], rhi[eff] = min(rlo[eff], real), max(rhi[eff], real)
                    shares.append(share)
                    realised.append(real)
                print(
                    f"{mean} {rho} {sd} | "
                    + " ".join(f"{s:.3f}" for s in shares)
                    + " | "
                    + " ".join(f"{r:.3f}" for r in realised[1:])
                )
    for eff in EFFECTS:
        print(
            f"added chance {eff:.2f}: rejected in {lo[eff]:.3f} to {hi[eff]:.3f} of waves over "
            f"the grid; realised effect {rlo[eff]:.3f} to {rhi[eff]:.3f}"
        )


if __name__ == "__main__":
    main()
