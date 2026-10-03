# Run 1 (archived, contains a labelling bug)

These are the run-1 files, moved here unchanged for run 2: results, the frozen split (seed 2026,
ids s0001..s0300), the dev-round log, the model reply cache and the call ledger. They were produced
by the code at commit 6ec958f (`git checkout 6ec958f -- bench/supersession` to rerun them with
`--cache-only`); the code in the parent directory has since changed.

Known bug: the category E (must not supersede) template "{E} keeps backups in {new}." was labelled
unrelated, but any entity could hold a `Backup region` fact, which that sentence does update. One
held-out note ("BasaltStack keeps backups in us-west-2.") hit this, and it was the single false
supersession every arm was charged with. Run 1 is still reported as a fail against its
pre-registered bar; the bug was found after the run. Run 2 removes the template and adds a
generator check (`audit_templates`, `check_cases` in `generate.py`) that refuses to generate a
negative note that touches an existing fact key of its entity.
