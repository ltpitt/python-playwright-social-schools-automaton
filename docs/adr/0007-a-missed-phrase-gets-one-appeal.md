# A missed phrase gets one appeal, and the judge can only acquit

Recall expectations are literal strings matched against the rendered Digest. That is exactly the right instrument for a date, a clock time, a group label or a name — facts the model copies rather than composes, where an exact match is close to a proof. It is the wrong instrument for everything a translator chooses: one Dutch noun may arrive as "raincoat" or "rain jacket", another as "packed lunch" or "lunch box", and a plural phrasing turns "group 3" into "groups 3 and 4" so the expectation no longer appears at all. Those are correct Digests failed on spelling.

So `evaluate_digests.py` puts a missed phrase to a model — `judge.py` — and asks a single question: does this Digest convey that information in any wording? A yes overturns the miss.

**Why an appeal court and not a first instance:**

- **It cannot make the gate stricter.** Only phrases the deterministic matcher already failed are ever put to it, and a verdict can only turn a miss into a hit. A judge that is wrong, biased, offline or absent can never fail a case that string matching passed. That asymmetry is what makes it safe to run unattended inside `goal.py`.
- **It is usually free.** Nothing is asked when every phrase is found, which is the common case. On the run that motivated this, three phrases out of roughly fifty would have gone to appeal.
- **The deterministic result is still the default.** `08:30` is decided by code. Only prose reaches a model.
- **Verdicts are cached** on `(model, digest, phrase)`, so a re-run costs nothing and two evaluations of the same product produce the same number. Without that, the ledger in `goal.py` would compare turns measured by a fluctuating ruler.
- **Any failure means no rescues.** An unreachable endpoint, an unparseable answer or a non-boolean verdict all leave the gate exactly as strict as it was. Fail-closed, because fail-open would silently pass everything.

**Why faithfulness is not judged:** `must_not_mention` is the mirror image — there a judge would be *adding* violations for paraphrased inventions. That is arguably more correct, and it is a different risk: a non-deterministic gate that can fail you is far worse than one that can forgive you, and it would put the loop at the mercy of a judge's mood. Faithfulness stays literal.

**Trade-off / consequences:**
- The evaluator now makes model calls, so `make eval` is no longer strictly offline. `--no-judge` (`make eval NOJUDGE=1`) restores that, and `make check` never ran eval, so CI is unaffected.
- The judge should be a different model from the one generating Digests — the maker should not mark its own work. `--judge-model` exists for that; by default it reuses the configured model, which is the weaker arrangement and the cheaper one.
- A judge is only as good as its agreement with you. Before trusting it on the holdout split, read a run's rescues and confirm you would have made the same calls. The rescues are printed in the case table for exactly this reason.
- It removes the incentive to write brittle expectations, but not the value of good ones. A phrase that names a fact rather than a wording still costs nothing and still runs offline.
