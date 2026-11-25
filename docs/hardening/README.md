# Hardening records

What the mutation sweeps of [`docs/process/testing.md`](../process/testing.md) ("Mutation testing")
found, kept by `scripts/mutate.py` and read by the hardening page of the Pages site
([`docs/process/ci.md`](../process/ci.md), "The Pages site"). Nothing here is written by hand.

`mutation/` holds, for each area of [`scripts/areas.py`](../../scripts/areas.py) that has been
swept:

- **`baseline-<area>.json`**: what the sweep was made from (the repository, the workflow runs, the
  commit and mutmut's version); the counts (`mutants`, `killed`, `timeout`, `survived`, `no tests`,
  `other`, `not run`); the same by file, with each file's `content`, its git blob at that commit, so
  a file changed since shows; and `dropped`, the tests left out of the area's runs, each with its
  traceback and kind, none once settled.
- **`survivors/<area>.json`**: its survivors, one a line in each module's order: mutmut's name for
  the change, its file, function and line, and the lines it removed and added.

`mutation/` is made by the first sweep, once a first pass of the code is written; until then the
measure is coverage alone.
