<!--
Thanks for contributing. One thing is asked of every change here that most
projects do not ask, and it is the same standard the library enforces on
agents: show that your tests can fail, not just that they pass.
-->

## What this changes

<!-- One or two sentences. What is different afterwards, in plain terms? -->

## Proof it can fail

Break the thing on purpose, confirm the right test goes red, restore, confirm
green. Paste both numbers:

```
before (broken on purpose):
after  (restored):
```

Green both before and after a change means the change is untested — that is
the failure this section exists to catch, and it has caught real ones here.

## Checklist

- [ ] `python -m pytest` passes
- [ ] `python tools/verify_wheel.py` passes (runs CI's installed-package job locally)
- [ ] A new gate ships at least one `Case(expect_flagged=True)` it is required to catch
- [ ] A new detection rule was swept over real code and the hits were read by eye
      (a gate that cries wolf gets switched off, and then everyone still
      believes it is running)
- [ ] Test and CI counts went up or stayed level, never down
