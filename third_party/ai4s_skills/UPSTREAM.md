# ai4s-skills source record

- Upstream: https://github.com/ai4s-research/ai4s-skills
- Vendored commit: `744ab2049a7b52ae726c43313468fd518b330980`
- License: MIT; see `LICENSE` in this directory.
- Included packages: `research-explorer`, `experiment-suite`, `integrity-auditor`, `mindmap-render`.

These packages are loaded as workflow references. Executable capabilities are
exposed only through the controlled adapters registered by this project.

Local patch: mindmap renderer falls back to installed Edge/Chrome when the
matching Playwright browser executable is missing. Other launch errors remain visible.
