# Security

This is a reference implementation and demo; it is not intended to protect real assets.

If you believe you found a vulnerability in the code, please open a private security advisory
on the GitHub repository (or contact the maintainer, via the address on the
GitHub profile) rather than a public issue. Include the version/commit, a description, and a
reproduction if possible. There is no SLA.

Please do not report findings that are already listed in `docs/production-gaps.md`; those are
known and deliberate limits of a reference.

Secrets: no real keys or credentials belong in this repository. Tests generate keys at run
time; the sample configuration uses placeholders and environment variables.
