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


def test_everything_shown_to_the_user_is_in_their_language_and_plain_words():
    assert "status lines between tool calls included" in SPECIALIST
    assert "stage names" in SPECIALIST and "never a command to run" in SPECIALIST


def test_folder_access_is_requested_in_the_same_task_with_the_old_sentence_as_a_fallback():
    start = " ".join(SPECIALIST.split("## Start of every session")[1].split("3. **Latest changes")[0].split())
    assert "mcp__cowork__request_cowork_directory" in start and "this same task" in start
    assert "not there or it fails" in start and "open a new task" in start
    assert start.index("mcp__cowork__request_cowork_directory") < start.index("open a new task")


def test_the_person_agrees_before_anything_runs_on_their_computer():
    build = " ".join(reference("build").split())
    assert "Wait for their yes" in build and "app_preview_stop" in build and "`starting`" in build
    assert build.index("Wait for their yes") < build.index("`app_preview(workspace)`")
    assert "except `app_preview`" in SPECIALIST


def test_the_risk_of_a_preview_is_said_where_it_is_decided():
    docs = Path(__file__).resolve().parents[2] / "docs"
    for page in ("decisions.md", "barriers.md", "configuration.md"):
        text = " ".join((docs / page).read_text(encoding="utf-8").split())
        assert "code an AI wrote and nobody has reviewed yet, on the person's computer, with their rights" in text, page
        assert "reduce that risk and do not remove it" in text, page


def test_no_skill_tells_claude_to_run_a_git_command_that_writes():
    for skill in SKILLS.rglob("*.md"):
        assert not re.search(r"`git (-C \S+(?: \S+)? )?(status|diff|stash)\b", skill.read_text(encoding="utf-8")), skill
