# gitAiOrchestrator Development Guidelines

Auto-generated from all feature plans. Last updated: 2026-05-23

## Active Technologies
- POSIX sh (`#!/bin/sh`) — no bash-isms; CI and interactive terminal compatible + git (already required by 001); no external packages (002-git-hook-scripts)
- N/A — logs written to `logs/hooks.log` (002-git-hook-scripts)

- Python 3.10+ + stdlib only (`subprocess`, `shutil`, `pathlib`, `sys`) — no third-party packages required (001-installer-setup)

## Project Structure

```text
src/
tests/
```

## Commands

cd src && pytest && ruff check .

## Code Style

Python 3.10+: Follow standard conventions

## Recent Changes
- 002-git-hook-scripts: Added POSIX sh (`#!/bin/sh`) — no bash-isms; CI and interactive terminal compatible + git (already required by 001); no external packages

- 001-installer-setup: Added Python 3.10+ + stdlib only (`subprocess`, `shutil`, `pathlib`, `sys`) — no third-party packages required

<!-- MANUAL ADDITIONS START -->
<!-- MANUAL ADDITIONS END -->
