# Synthetic robustness evaluation

`python scripts/eval_synthetic.py` runs a seeded, clearly labelled SYNTHETIC
smoke evaluation for the open-ended detector path. It is intentionally not a
real-company performance claim. The current harness covers the robust-outlier
injection and is a starting point for the held-out multi-case evaluation
planned in P3. Thresholds must not be tuned on held-out seeds.
