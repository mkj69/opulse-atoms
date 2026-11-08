"""Seeded simulation of confidence interval half-widths for episode accuracy."""

import argparse
import math
import random

from .decision import SEED, percentile


def simulate_half_width(mean, sd, episodes, simulations=10000, seed=SEED):
    """Simulate the sampling distribution of the B-C difference of means."""
    if episodes < 1 or simulations < 1 or sd < 0:
        raise ValueError("episodes and simulations must be positive; sd must be nonnegative")
    rng = random.Random(seed)
    draws = [sum(rng.gauss(mean, sd) - rng.gauss(mean, sd)
                 for _ in range(episodes)) / episodes for _ in range(simulations)]
    return {"ci90_half_width": (percentile(draws, 0.95) - percentile(draws, 0.05)) / 2,
            "ci95_half_width": (percentile(draws, 0.975) - percentile(draws, 0.025)) / 2,
            "standard_error": sd * math.sqrt(2 / episodes)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mean", type=float, default=0.5)
    parser.add_argument("--simulations", type=int, default=10000)
    args = parser.parse_args(argv)
    print("N  SD    SE     90% half-width  95% half-width")
    for episodes in (20, 40, 60):
        for sd in (0.15, 0.25, 0.35):
            result = simulate_half_width(args.mean, sd, episodes, args.simulations)
            print(f"{episodes:<2} {sd:.2f}  {result['standard_error']:.3f}  "
                  f"{result['ci90_half_width']:.3f}           {result['ci95_half_width']:.3f}")


if __name__ == "__main__":
    main()
