"""The specialist's rules that came from testing it with people: a rule that is lost here comes back as the same
failure in a real task. These read the skill as it ships; what the model does with it is checked in validation."""

import re
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2] / "plugin" / "skills"
SPECIALIST = (SKILLS / "specialist" / "SKILL.md").read_text(encoding="utf-8")


def reference(stage: str) -> str:
    return (SKILLS / "specialist" / "references" / f"{stage}.md").read_text(encoding="utf-8")


def test_the_specialist_never_runs_git_in_the_workspace():
    assert "Never run git in the workspace" in SPECIALIST
    assert "`.git`" in SPECIALIST


def test_a_refused_send_is_never_explained_away():
    deliver = reference("deliver")
    assert "`audit_refused`" in deliver and "`audit_unavailable`" in deliver and "Never explain" in deliver
    assert "list it in the pull request" not in reference("build")  # a refused version has no pull request


def test_a_question_not_answered_means_wait():
    assert "A question not answered means wait" in SPECIALIST
    assert "No default is taken in the user's name" in SPECIALIST
    assert "and move on" not in reference("understand")  # the way "no preference, I take the recommended one" came in


def test_no_skill_tells_claude_to_run_a_git_command_that_writes():
    for skill in SKILLS.rglob("*.md"):
        assert not re.search(r"`git (-C \S+(?: \S+)? )?(status|diff|stash)\b", skill.read_text(encoding="utf-8")), skill
