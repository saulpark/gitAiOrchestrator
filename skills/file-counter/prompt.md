Count every file in the repository and summarise them by file type.

Scope:

- enumerate all files in the repository with Glob, including untracked and
  gitignored ones. Glob truncates large result sets, so glob each top-level
  directory separately (in parallel) and de-duplicate;
- skip everything under `.git/` — it is git's internal storage, not project
  files.

A file's type is its extension (e.g. `.py`, `.md`); files without one are
`(none)`. Do not read files and do not count lines — only the file list is
needed.

Report in markdown:

1. A one-line total: the number of files.
2. A table sorted by file count, descending:

   | Type | Files | % of files |
   |------|-------|------------|

   with a final **Total** row.
3. A short note listing which of the changed files of this event exist, so the
   reader can see what triggered the run.

If you could not enumerate every file within the budget, say so explicitly.

This skill is informational: the verdict is always `pass`.
