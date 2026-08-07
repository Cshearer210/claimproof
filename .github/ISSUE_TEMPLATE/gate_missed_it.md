---
name: A gate let something through
about: Text or code that should have been caught and was not
title: 'Missed: '
labels: bug
---

**The text or code that got through** — paste it exactly.

```
```

**Which gate should have caught it**: <!-- UnbackedClaims / TypedScope / SilentSkip / NothingLeft -->

**What it should have said** — in your words, what is wrong with the sample above.

**Version**: `python -c "import claimproof; print(claimproof.__version__)"`

<!--
Fixing a miss is the easier half; the hard half is fixing it without starting
to flag correct work. A pull request that widens a rule should show the sweep
over real code and the flag rate before and after.
-->
