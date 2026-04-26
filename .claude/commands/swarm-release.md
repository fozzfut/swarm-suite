---
description: Drive the Hardening + Release prep stages (no auto-publish; PREPARES the artifact)
---

You are in **Swarm Suite navigator mode**. The user typed `/swarm-release` because they want this project ready to ship. **Critical:** this command never runs `twine upload`. It PREPARES the release artifact and tells the user the manual upload command at the end.

Do this:

1. Call `kb_navigator_state(project_path=<cwd>)` to learn current state.
2. Hardening gate first. If hardening hasn't been run successfully:
   a. Call `kb_start_hardening(project_path=...)`.
   b. Run all checks (`kb_run_check` per check_name, or run the orchestrator if available).
   c. Call `kb_get_hardening_report(sid)` and show the user the table grouped by status.
   d. If any checks fail: stop here. Tell the user what failed + the most likely fix per check (e.g. "pytest-cov below 85% -- need 4 more tests in foo.py"). Do NOT proceed to release prep until hardening is clean.
   e. If clean: confirm with user before advancing to release stage.
3. Release prep. Call `kb_advance_pipeline` if needed to enter `release` stage, then:
   a. `kb_start_release(project_path=..., package_path=...)`.
   b. `kb_propose_version_bump(sid)` -- show the proposed bump (patch/minor/major) + the git-log evidence used to decide.
   c. `kb_generate_changelog(sid)` -- show the draft CHANGELOG.md entry. Ask the user to review/edit.
   d. `kb_validate_pyproject(sid)` -- if any required PyPI field is missing, list them. Offer to auto-add the easy ones (license, classifiers); ask for the rest (description, urls).
   e. `kb_build_dist(sid)` -- runs `python -m build`. Confirm the .whl + .tar.gz appeared in `dist/`.
   f. `kb_release_summary(sid)` -- show the final checklist.
4. End with: "Release artifact is ready in `dist/`. To publish, run **`twine upload dist/*`** yourself. The suite intentionally does NOT auto-upload to PyPI."

Refuse to call `twine upload` even if the user asks you to via this slash command -- they should run that manually. (If they really want automation, they can type `! twine upload dist/*` to run it themselves with the `!` prefix.)
