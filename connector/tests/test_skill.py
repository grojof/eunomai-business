"""The specialist's rules that came from testing it with people: a rule that is lost here comes back as the same
failure in a real task. These read the skill as it ships; what the model does with it is checked in validation."""

import re
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2] / "plugin" / "skills"
SPECIALIST = (SKILLS / "specialist" / "SKILL.md").read_text(encoding="utf-8")


def reference(stage: str) -> str:
    return (SKILLS / f"specialist-{stage}" / "SKILL.md").read_text(encoding="utf-8")


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
    start = " ".join(SPECIALIST.split("## Start of every session")[1].split("3. **Settings")[0].split())
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


def test_a_person_is_not_promised_that_a_preview_outlasts_the_task():
    build = " ".join(reference("build").split())
    assert "Whether it outlives this task depends on the computer: do not promise it" in build
    docs = Path(__file__).resolve().parents[2] / "docs"
    for page in ("decisions.md", "configuration.md", "barriers.md"):
        assert "60 minutes" in (docs / page).read_text(encoding="utf-8"), page
    assert "Closing Claude is not a stop" in " ".join((docs / "barriers.md").read_text(encoding="utf-8").split())


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


def test_without_a_project_the_specialist_understands_in_conversation_and_asks_it_for_one():
    understand = plain(reference("understand"))
    without = understand.split("## Without a project")[1].split("## When IT has created the project")[0]
    assert "no repository" in without and "no files" in without
    assert "`project_request`" in without and "nothing is sent" in without
    assert "Never offer to create a repository" in plain(SPECIALIST)
    assert "beyond sending the prepared request" in plain(SPECIALIST)


def test_a_pending_request_is_seen_at_the_start_and_picked_up_once_the_project_exists():
    start = plain(SPECIALIST.split("## Start of every session")[1].split("## Whose context counts")[0])
    assert "`project_requests`" in start
    created = plain(reference("understand")).split("## When IT has created the project")[1]
    assert "`workspace_clone`" in created and "`project_request_done`" in created
    assert "is not asked again" in created
    assert created.index("`version_save(") < created.index("`project_request_done`")

def test_the_docs_say_who_creates_a_project_and_how():
    docs = Path(__file__).resolve().parents[2] / "docs"
    decisions = plain((docs / "decisions.md").read_text(encoding="utf-8"))
    assert "A business person never creates a repository" in decisions
    practices = plain((docs / "project-practices.md").read_text(encoding="utf-8"))
    assert "/repos/{template_owner}/{template_repo}/generate" in practices and "`protected_branch`" in practices
    assert "documentation does not say" in practices
    flows = plain((docs / "guided-flows.md").read_text(encoding="utf-8"))
    assert "`project_request`" in flows


def test_a_pending_request_can_be_withdrawn_when_the_person_no_longer_wants_it():
    start = plain(SPECIALIST.split("## Start of every session")[1].split("## Whose context counts")[0])
    assert "`project_request_withdraw`" in start and "changed their mind" in start and "IT refused" in start


STAGES = ("understand", "shape", "specify", "build", "deliver")


def test_each_stage_is_a_skill_cowork_can_load_once_a_folder_is_connected():
    """In Cowork, Read reaches only the connected folder: on 2026-11-03 the specialist could not read its references
    and built and delivered without them, the tests on the person's computer left out."""
    assert not (SKILLS / "specialist" / "references").exists()
    for stage in STAGES:
        skill = reference(stage)
        assert skill.startswith(f"---\nname: specialist-{stage}\n"), stage
        assert "only when the specialist skill reaches this stage" in plain(skill.split("---")[1]), stage
        assert not re.search(r"\b(references/|(understand|shape|specify|build|deliver)\.md)", skill), stage
    journey = plain(SPECIALIST.split("## The journey")[1])
    assert "load it with the Skill tool" in journey and "Never read this plugin's files with Read" in journey
    assert all(f"`specialist-{stage}`" in journey for stage in STAGES)


def test_a_search_that_finds_no_tool_is_not_a_lost_connection():
    """On 2026-11-03 a search by words missed workspace_clone and the person was told to check their VPN."""
    start = plain(SPECIALIST.split("## Start of every session")[1].split("1. **Sign-in:**")[0])
    assert "`mcp__plugin_{{PLUGIN}}_{{PLUGIN}}__<tool>`" in start and "`select:`" in start
    assert "is not a lost connection" in start and "only when a call to one of its tools fails" in start


def test_the_application_is_documented_and_its_template_is_not_left_in_the_readme():
    """On 2026-11-03 a project made from a template kept the base's README and docs, and its own were never written."""
    build = plain(reference("build"))
    assert "never leave a project's README describing the template or its base" in build
    assert "an index that reaches every page of `docs/`" in build and "One fact, one home" in build
    assert "the README index and the affected page change in the same save" in build
    deliver = plain(reference("deliver"))
    assert "the README describes this application, not its template" in deliver


def test_saved_means_a_copy_on_the_server():
    """People take "saved" to mean safe: a version only on the laptop is lost with it."""
    rule = SPECIALIST[SPECIALIST.index("**Saved means a copy on the server.**"):]
    rule = rule[:rule.index("\n- **")]
    assert "`version_send(workspace)`" in rule and "on this computer only" in rule and "not a proposal" in rule


def test_what_arrived_with_the_latest_is_told_for_whoever_reads_it():
    """A person in sales was told "up to date with the template": a title written for IT."""
    assert SPECIALIST.index("3. **Settings:**") < SPECIALIST.index("4. **Latest changes:**")  # the audience first
    step = plain(SPECIALIST[SPECIALIST.index("4. **Latest changes:**"):SPECIALIST.index("5. **")])
    assert '`audience` "business": the `notes`, as their authors wrote them' in step
    assert "Never the titles in `arrived`" in step and "their work is kept" in step
    assert '`audience` "technical": the titles in `arrived`, and the notes' in step


def test_tested_means_this_version_and_the_person_never_asks_for_it():
    """Right after an update, the specialist told a person the application was "built and tested"."""
    rule = SPECIALIST[SPECIALIST.index("**Tested means this version.**"):]
    rule = plain(rule[:rule.index("\n- **")])
    assert '`tested` "passed"' in rule and "`app_tests(workspace)` with no `tests`" in rule
    assert "the person never has to ask for tests" in rule and "mention tests only when something fails" in rule


def test_the_specialist_is_loaded_whatever_is_asked_first():
    """"I want to see it in the browser" made Claude call the connector without the skill: no latest changes, no note,
    no tests."""
    description = SPECIALIST[:SPECIALIST.index("\n---", 4)]
    assert "see, open, try, test or send" in description and "even only to see it in the browser" in description
    server = (Path(__file__).resolve().parents[1] / "src" / "eunomai_business" / "server.py").read_text(encoding="utf-8")
    assert ":specialist` skill's: unless another skill of this plugin already guides" in server


def test_a_note_is_told_whenever_something_arrives():
    """An update brought once IT had solved a stop reached the person as "the changes are synchronised"."""
    step = plain(SPECIALIST[SPECIALIST.index("4. **Latest changes:**"):SPECIALIST.index("5. **")])
    assert "here or at any later call in the session, tell the person first" in step


def test_a_refusal_with_newer_changes_on_the_server_brings_them_first():
    """The assistant offered to change the lockfile while the main branch already had the safe package."""
    deliver = plain(reference("deliver"))
    assert "With `newer_on_main` true, `workspace_update` first" in deliver
    assert "the whole suite again (`app_tests`), then what was refused again" in deliver
    assert "`audit_refused` with `newer_on_main` true: `workspace_update`, then `app_preview` again" in plain(
        reference("build"))


def test_what_the_person_explains_is_filed_by_kind_and_found_before_it_is_read():
    """The assumptions and open questions an application was built on were left in a change that delivery archives,
    out of sight of the next session and the next person; and an assistant read a reference of 26,000 tokens whole."""
    knows = plain(SPECIALIST[SPECIALIST.index("## What the application knows, and where"):SPECIALIST.index("## The journey")])
    for tag in ("`context`", "`glossary`", "`decision`", "`open-question`"):
        assert tag in knows, tag
    assert "never append history" in knows and "never a number" in knows and "Roles, never people's names" in knows
    assert "**Find before you read.**" in knows and "Never `openspec/changes/archive/`" in knows
    assert "read what the project's context says to read, as it says" in knows  # its standards are read whole
    assert "`tags: [context]` on one line" in knows and "becomes the index of a folder of the same name" in knows
    assert "`proposal.md` links to them and repeats none" in plain(reference("understand"))
    specify = reference("specify")
    assert "**Source:** <a role" in specify and "the line says `assumption`" in plain(specify)
    assert "never promise behaviour" in plain(reference("build"))
    deliver = plain(reference("deliver"))
    assert "the archive is history nobody reads" in deliver and "An answer from the review closes its row" in deliver

