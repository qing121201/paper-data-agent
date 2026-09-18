# NatureSkills vendor provenance

- Upstream: https://github.com/Yuan1z0825/nature-skills
- Commit: `9ea7330a17813a15421fe843778a776c258b9001`
- Commit date: 2026-09-14T03:02:47Z
- Imported: 2026-09-15
- License: Apache License 2.0; see `LICENSE` in this directory.

The directories here are copied upstream skill packages for this course demo.
They are loaded as declarative workflow text. The Paper Data Agent does not
automatically execute commands found in third-party skill files.

Local integration patch: `nature-academic-search/scripts/academic_search.py`
keeps the complete OpenAlex inverted-index abstract instead of the upstream
500-character display truncation. This changes evidence display only, not search
ranking or metadata.

The same integration also preserves OpenAlex landing URL, work type and
retraction status so the local homepage can verify that a recommended page
still exists before presenting it to the user.
