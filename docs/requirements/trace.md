# Requirements and the tests that show them

Every sentence of a requirement either promises something observable or explains. A promise nobody
shows is a decision recorded but never built. This file ties each sentence of a traced section to
what shows it, and `tests/test_requirements_trace.py` splits each traced section into sentences
(and table rows) the way this file does, and fails when a sentence has no row, a row no longer
matches its sentence, or a row names a test or an issue that isn't there
([`../process/testing.md`](../process/testing.md), "Principles").

A section joins when its code is built, with the slice that builds it (`DEVELOP.md`), as a
`## N. Title` heading here and a row per sentence under it; every section of the first release is
here by that release.

**Shown by** names, comma-separated:

- a test function (`test_…`, found in `tests/`);
- `tier 3: ` and the check a person makes, when only a person can show it (testing.md, "Tiers");
- `later: #n`, the `future` issue the sentence waits on;
- `statement`: it explains, names a file or a limit, and promises nothing a test could show.

**Sentence starts** is the sentence's opening words, with Markdown emphasis and backticks dropped.
A table row is traced whole, its cells as written.
