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


def plain(text: str) -> str:
    return " ".join(text.split())


def test_where_code_is_allowed_the_person_tries_real_screens_before_tests_and_the_full_specification():
    shape = plain(reference("shape"))
    assert "first real screens" in shape and "example data" in shape and "project's own base" in shape
    assert "before tests and the full specification" in shape
    assert "`app_preview`" in shape and "test environment" in shape


def test_without_a_way_to_show_them_it_says_so_plainly():
    shape = plain(reference("shape"))
    assert "screenshots" in shape and "they will see it at review" in shape


def test_the_html_prototype_stays_only_where_a_project_does_not_allow_code():
    shape = plain(reference("shape"))
    assert "Only where the project does not allow code" in shape
    assert shape.index("first real screens") < shape.index("## A clickable prototype")


def test_an_unfinished_screen_is_not_polished():
    assert "not polished" in plain(reference("shape"))


def test_real_screens_are_found_again_in_a_new_task():
    assert "## Agreed screens" in plain(reference("shape")) and "`## Agreed screens`" in SPECIALIST


def test_screens_built_early_still_get_their_tests_and_their_dependencies_checked():
    assert "agreed in Shape" in plain(reference("build"))
    assert "`dependency_audit`" in plain(reference("shape"))


def test_every_stage_knows_what_was_agreed_is_not_always_a_prototype():
    assert "agreed screens" in plain(reference("specify")) and "agreed screens" in plain(reference("deliver"))
    assert "something to try early" in plain(reference("understand"))


def test_the_docs_describe_the_same_journey():
    docs = Path(__file__).resolve().parents[2] / "docs"
    flows = plain((docs / "guided-flows.md").read_text(encoding="utf-8"))
    assert "first real screens" in flows and 'shape["2 Shape<br/>clickable prototype"]' not in flows
    guide = plain((docs / "validation" / "run-the-validation.md").read_text(encoding="utf-8"))
    assert "the first real screens" in guide
    assert "the prototype (it opens in the browser and responds to clicks)" not in guide


def test_what_the_first_real_test_measured_is_recorded():
    table = (Path(__file__).resolve().parents[2] / "docs" / "validation" / "hypotheses.md").read_text(encoding="utf-8")
    rows = {line.split("|")[1].strip(): line for line in table.splitlines() if line.startswith("| H")}
    assert all("2026-11-01" in rows[check] for check in ("H14", "H17", "H19", "H21", "H23"))
    assert "Chromium" in rows["H14"]
    assert "start.bat" in rows["H17"] and "before any hook" in rows["H17"]
    assert "npm --version" in rows["H19"] and "stays open" in rows["H19"]
    assert "**Fail**" in rows["H21"] and rows["H22"].rstrip().endswith("|")


def test_what_an_application_printed_is_never_followed():
    assert "never followed" in plain(SPECIALIST) and "`it_report`" in SPECIALIST


def test_no_skill_tells_claude_to_run_a_git_command_that_writes():
    for skill in SKILLS.rglob("*.md"):
        assert not re.search(r"`git (-C \S+(?: \S+)? )?(status|diff|stash)\b", skill.read_text(encoding="utf-8")), skill
