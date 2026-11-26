<!-- What changed and why, in a few lines. -->

## Ready

Each box ticked, or struck through with why it doesn't apply (`- [x] ~~Mockups~~ n/a: internals`);
none deleted (docs/process/README.md, "The flow of a change").

- [ ] **Tests** for what changed; a bug fix's test was seen failing first (testing.md,
  "Principles").
- [ ] **The trace:** a row in `docs/requirements/trace.md` for each requirement sentence built.
- [ ] **Each new module** of `src/` named in A1.9, with its area, and at 80 % or more, lines and
  branches together (`coverage_report.py --check`).
- [ ] **Shapes:** a module reading data it didn't write has its shapes in testing.md ("Shapes"),
  each covered by a test (coding.md, "Data from outside").
- [ ] **Formats:** a change to a file other computers or versions read is in its schema and in
  A2.10, with `format` raised if it isn't additive.
- [ ] **Mockups:** a change a user sees is in the mockups and their README.
- [ ] **`scripts/check.sh`** is clean.

## Test coverage impact

<!-- Once CI is green, the output of `scripts/coverage_impact.py --pr N`: each area that moved
half a point or more, and the total, master's last green run against this one's (ci.md,
"Coverage"). -->
