---
name: project-spike
description: Runs the H10 test of an eunomai-business project plugin. Use only when the user asks to run the project spike test.
---

# Project spike (H10)

A test, not a feature. Run these steps in order and show every tool's answer whole, as returned.

1. This plugin's own server: `project_ping`.
2. eunomai-business's connector, called from this skill: `whoami("git")` and `workspace_list`.
3. eunomai-business's settings for the first workspace listed, if any: `specialist_settings(<its name>)`. Show its
   `project_context` field only.
4. The project hook's log: `project_guard_log`.

Then a table: step, tool's full name as you called it, worked (yes or no). Nothing else.
