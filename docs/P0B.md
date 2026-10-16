# P0-b calculator and scanner

The calculator consumes only stored `facts`. Fiscal quarters are treated as Indian fiscal
quarters (Q1 April-June through Q4 January-March). Restated facts take precedence while
their fact IDs remain available for audit.

## Formulas

* Loan growth YoY = current-quarter advances / same quarter prior year - 1.
* GNPA% = gross NPA / gross advances * 100.
* NNPA% = net NPA / gross advances * 100.
* PCR = provisions on NPA / gross NPA * 100.
* Slippage ratio = annualised fresh slippages / opening advances * 100.
* Credit cost = annualised (provisions + write-offs) / average advances * 100.
* Write-off-adjusted GNPA = (GNPA + trailing-four-quarter write-offs) /
  (advances + trailing-four-quarter write-offs) * 100.
* Stage 2% and Stage 3% = stage balance / advances * 100.
* CASA ratio = CASA deposits / total deposits * 100.
* Credit-deposit ratio = gross advances / total deposits * 100.

Missing inputs yield `NaN` and a reason; no fallback arithmetic is performed. Each metric and
anomaly carries the contributing source `fact_id` values. Peer checks require three peers
with data and otherwise report `insufficient`.

R1-R4 are declared in `config/anomaly_rules.yaml`; scores combine normalised magnitude,
persistence, peer divergence, and novelty. Novelty is deliberately zero with a TODO until
the later reasoning stage.
