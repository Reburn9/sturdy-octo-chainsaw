# Metric definitions

Every dataset fixes a review target `n` between two and five. A uniqueness constraint ensures that each user has at most one current vote per record, and the workflow prevents votes beyond the target. Incomplete records are excluded from agreement denominators, rather than treated as disagreements or successes.

## Coverage and decision readiness

- **Review coverage:** target-complete records / all records. A disputed record is fully reviewed even if it is not ready for export.
- **Unanimous agreement:** target-complete records with a single independent label / target-complete records. Adjudication does not change the independent votes.
- **Decisions ready:** unanimously agreed records plus manager-adjudicated records.
- **Distribution:** every submitted independent vote, including votes on incomplete records. This denominator is displayed next to the distribution.

When there are no complete records, agreement is `null` in the API and an em dash in the interface. Zero is a measured score, not a substitute for missing data.

## Fleiss' kappa

For `N` complete records and `n` votes per record, let `n_ij` be the votes for category `j` on record `i`.

```text
P_i   = sum_j n_ij (n_ij - 1) / (n (n - 1))
P_bar = mean_i P_i
p_j   = sum_i n_ij / (N n)
P_e   = sum_j p_j²
kappa = (P_bar - P_e) / (1 - P_e)
```

The API's `pairwise_agreement` is `100 * P_bar`. `fleiss_kappa` is rounded to four decimal places. If there are no complete records, or all votes fall into one category so the denominator is zero, kappa is `null`. A negative kappa is retained; it is not clamped to zero.

For two records with votes `[positive, negative]` and `[positive, positive]`, unanimous agreement and pairwise agreement are both 50%. Category proportions are 0.75 and 0.25, expected agreement is 0.625, and kappa is -1/3. The tests verify this example and verify that adjudication does not alter it.

Kappa describes agreement beyond the observed category marginal distribution. It is not accuracy against a gold standard, and a higher score alone does not establish labeling correctness. Reviewers must still use domain-specific guidelines and inspect ambiguous cases.
