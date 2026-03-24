# Swarm-Suite Installation & Upgrade Issues

Encountered during pip install, pip->uv migration, and MCP server usage on Windows 10/11.
Date: 2026-03-24. User: adminSID.

---

## 1. pip uninstall leaves corrupted `~` directories

**Symptom:** After `pip uninstall <pkg>`, directories with `~` prefix remain in `site-packages/`:
```
~eview_swarm/
~eview_swarm-0.3.7.dist-info/
~oc_swarm_ai-0.1.6.dist-info/
~rch_swarm/
~rch_swarm_ai-0.1.6.dist-info/
~warm_kb/
~warm_kb-0.2.1.dist-info/
~warm_kb-0.2.6.dist-info/
```

**Cause:** pip renames dirs to `~<name>` during uninstall, then deletes. If the process is interrupted (exe locked, permission error), the `~` dirs remain as garbage.

**Locations affected:**
- `C:\Users\<user>\AppData\Local\Programs\Python\Python312\Lib\site-packages\`
- `C:\Users\<user>\AppData\Roaming\Python\Python312\site-packages\`

**Impact:** Disk clutter. No runtime impact (Python ignores `~` dirs), but confusing.

**Fix needed in installer:** Post-uninstall cleanup of `~*` dirs in both site-packages locations.

---

## 2. exe shims locked by MCP server processes — cannot uninstall or delete

**Symptom:** `pip uninstall` fails with exit code 2. Manual `rm` fails with "Device or resource busy":
```
rm: cannot remove '.../Scripts/review-swarm.exe': Device or resource busy
```

**Cause:** Claude Code spawns MCP servers as long-running processes using the exe shims in `Python312/Scripts/`. Windows locks open exe files. pip cannot remove them, and the uninstall partially fails.

**Processes found (14 total):**
- 3x review-swarm.exe
- 3x swarm-kb.exe
- 2x arch-swarm.exe
- 3x doc-swarm.exe
- 3x fix-swarm.exe

**Why multiple per package:** Claude Code restarts crashed MCP servers, and old instances may linger as zombies.

**Fix needed in installer:**
- Detect and kill running MCP server processes before uninstall/upgrade
- Or: installer should gracefully handle locked exe (retry after kill, or schedule delete on reboot)
- Consider: `MoveFileEx` with `MOVEFILE_DELAY_UNTIL_REBOOT` flag for stubborn locks

---

## 3. Stale exe shims shadow uv tool installs

**Symptom:** After pip uninstall + uv tool install, running `review-swarm` gives `ModuleNotFoundError`:
```
ModuleNotFoundError: No module named 'review_swarm'
```

**Cause:** pip uninstall removed the package but left the exe shim in `Python312/Scripts/`. Since `Scripts/` is earlier in PATH than `~/.local/bin/`, the stale exe is found first. It tries to import the now-deleted module and crashes.

**PATH order:**
1. `C:\Users\<user>\AppData\Local\Programs\Python\Python312\Scripts\` (pip — STALE)
2. `C:\Users\<user>\.local\bin\` (uv tool — CORRECT)

**Fix needed in installer:**
- Migration script must explicitly delete old exe shims from `Python312/Scripts/` after pip uninstall
- Or: installer should check for and warn about PATH shadowing
- Or: uv tool install should detect conflicting exe in PATH and warn

---

## 4. pip dual-location installs

**Symptom:** Same package installed in both system and user site-packages. Single `pip uninstall` only removes one.

**Cause:** Mix of `pip install` (user) and `pip install --user` or different pip configs. Two uninstall passes needed.

**Locations:**
- System: `C:\Users\<user>\AppData\Local\Programs\Python\Python312\Lib\site-packages\`
- User: `C:\Users\<user>\AppData\Roaming\Python\Python312\site-packages\`

**Fix needed in installer:** Check both locations and clean both during uninstall/migration.

---

## 5. pip uninstall partially fails silently

**Symptom:** `pip uninstall -y` returns exit code 2 but removes some files. No clear indication of what was left behind.

**Cause:** When exe is locked, pip removes the package metadata and most files but cannot remove the exe. Exit code is non-zero but the error is buried in output.

**Fix needed in installer:** Don't trust pip exit code alone. Post-uninstall verification: check that no exe remains in `Scripts/`, no dirs remain in `site-packages/`.

---

## 6. MCP config uses absolute paths — fragile across install methods

**Observed:** MCP config in `~/.claude/settings.json` uses absolute paths:
```json
"command": "C:\\Users\\adminSID\\.local\\bin\\review-swarm.exe"
```

**Risk:** If install method changes (pip -> uv, or different Python version), paths break.

**Recommendation:** Use bare command names (`review-swarm`) in MCP config, relying on PATH resolution. Only works if PATH is correctly configured.

---

## 7. arch-swarm scans git worktree directories

**Symptom:** arch-swarm analysis picks up files from `.worktrees/` and `.claude/worktrees/` directories, inflating scan results with duplicate/stale code.

**Fix needed:** Respect `.gitignore` or add explicit `--exclude` patterns. Default exclusions should include `.worktrees/`, `.claude/`, `node_modules/`, etc.

---

## Environment Details

- OS: Windows 10 Pro 10.0.19045
- Python: 3.12 (system install at `C:\Users\adminSID\AppData\Local\Programs\Python\Python312\`)
- uv: installed, `uv tool` functional
- Claude Code: MCP server integration, spawns swarm exe as long-running processes
- Shell: Git Bash (MSYS2)
