# Digging strategy v1

The archaeologist's playbook. Hunter divergences add to it through gated versions.

1. Exercise every endpoint seen in the evidence with a normal request first.
2. Change one field at a time, so a behavior change has one possible cause.
3. For each input field, try it missing, null, and of the wrong type.
4. Record the exact status code and body of every error.
5. A claim is OBSERVED only when a probe's response directly confirms it. Otherwise it stays INFERRED.
6. Prefer a probe that could refute the claim over one that can only confirm it.
