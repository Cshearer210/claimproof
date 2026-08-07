---
name: A gate flagged correct work
about: The most serious bug this project can have
title: 'False positive: '
labels: bug
---

<!--
A gate that flags correct work is worse than no gate: it gets switched off,
and then everyone still believes it is running. This is the highest-priority
bug category here, so thank you for reporting it.
-->

**The text or code that was flagged** — paste it exactly. It usually becomes a
permanent must-pass fixture, so your report turns straight into a regression test.

```
```

**Which gate**: <!-- UnbackedClaims / TypedScope / SilentSkip / NothingLeft / other -->

**What it said**:

```
```

**Why it is correct work** — one or two sentences on what the code or text was
actually doing.

**Version**: `python -c "import claimproof; print(claimproof.__version__)"`
