"""What a review of the preview a person keeps open found: what answers at its address, what a removal leaves, what
a summary claims, what the application can do to the environment it keeps, and the hour."""

import json
import os
import socket
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx
import pytest
from test_app_tests import RUNNER, declaration_of_tests, project_with_tests, run, tests_on  # noqa: F401
from test_preview import LOCK, browser, folders, nothing_left_behind, pids, show, turned_on  # noqa: F401
from test_preview_live import LIVE, change, live_declaration, live_project, steps, wait_for  # noqa: F401

from eunomai_business import gitops, preview, server as tools, settings, watcher

needs_uv = pytest.mark.skipif(not (os.environ.get("UV") or preview.shutil.which("uv")), reason="needs uv")
WINDOWS = sys.platform == "win32"


# --- 1: what answers at the address is the preview's own -------------------------------------------------------------

def foreign_listener() -> tuple[socket.socket, threading.Event]:
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    ending = threading.Event()

    def serve():
        while not ending.is_set():
            try:
                connection, _ = listener.accept()
            except OSError:
                return
            connection.recv(100)
            connection.sendall(b"HTTP/1.0 200 OK\r\n\r\nnot the application")
            connection.close()

    threading.Thread(target=serve, daemon=True).start()
    return listener, ending


@pytest.mark.preview
@needs_uv
def test_a_program_outside_the_tree_at_the_address_is_never_handed_to_the_person(signed_in, workspaces, turned_on,
                                                                                  browser, pids, monkeypatch):
    """It took the port first: the application cannot listen, and what answers is someone else."""
    listener, ending = foreign_listener()
    taken = listener.getsockname()[1]
    monkeypatch.setattr(preview, "_free_port", lambda: taken)
    try:
        name, _ = live_project(signed_in, pids)
        answer = show(name)
    finally:
        ending.set()
        listener.close()
    assert answer["status"] == "needs_it", answer
    assert "another program" in answer["user_message"] and "port" not in answer["user_message"].lower()
    assert browser == []


def test_the_owners_of_a_listening_port_are_read_from_netstat():
    lines = ["  TCP    127.0.0.1:5000         0.0.0.0:0              LISTENING       4242",
             "  TCP    127.0.0.1:5000         127.0.0.1:61000        ESTABLISHED     4242",
             "  TCP    0.0.0.0:6000           0.0.0.0:0              ESCUCHANDO      77",
             "  TCP    [::1]:5000             [::]:0                 LISTENING       99"]
    assert preview._windows_listeners(lines, 5000) == {4242, 99}
    assert preview._windows_listeners(lines, 7000) == set()


def test_the_owners_of_a_listening_port_are_read_from_proc(tmp_path):
    table = ("  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n"
             "   0: 0100007F:1388 00000000:0000 0A 00000000:00000000 00:00000000 00000000  1000        0 31337 1\n"
             "   1: 0100007F:1388 0100007F:EE48 01 00000000:00000000 00:00000000 00000000  1000        0 31338 1\n")
    assert preview._linux_listening_inodes([table], 5000) == {"31337"}


# --- 2: what a removal leaves --------------------------------------------------------------------------------------

def read_only_tree(root: Path) -> Path:
    inner = root / "data" / "inner"
    inner.mkdir(parents=True)
    file = inner / "kept.db"
    file.write_text("x")
    file.chmod(stat.S_IREAD)
    if not WINDOWS:
        inner.chmod(stat.S_IREAD | stat.S_IEXEC)
    return root


def test_a_removal_takes_read_only_files_and_folders_too(tmp_path):
    root = read_only_tree(tmp_path / "preview")
    assert preview._remove(root, wait=1.0) and not root.exists()


def test_the_watcher_removes_read_only_files_and_folders_too(tmp_path):
    root = read_only_tree(tmp_path / "watched")
    assert watcher.remove_tree(str(root), tries=5) and not root.exists()


def test_a_stop_that_could_not_clear_says_so(monkeypatch):
    kept = preview._keep("cannot-clear")
    (kept / "data").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(preview, "_remove", lambda folder, wait=10.0: False)
    answer = preview.stop("cannot-clear")
    monkeypatch.undo()
    preview._remove(kept)
    assert "could not" in answer["user_message"] and answer.get("cleared") is False, answer


@pytest.mark.preview
@needs_uv
def test_a_fresh_start_that_could_not_clear_the_data_says_so_and_does_not_pretend(signed_in, workspaces, turned_on,
                                                                                   pids, monkeypatch):
    name, _ = live_project(signed_in, pids)
    show(name)
    monkeypatch.setattr(preview, "_forget_kept", lambda workspace: False)
    answer = tools.app_preview(name, fresh=True)
    assert answer["status"] == "needs_it" and "could not be cleared" in answer["user_message"], answer


# --- 3: a summary leads with what the exit code says ----------------------------------------------------------------

@pytest.mark.preview
@needs_uv
def test_counts_that_contradict_the_exit_code_never_lead(signed_in, workspaces, tests_on):
    name = project_with_tests(signed_in, RUNNER_FAILURES="0", RUNNER_EXIT="1")
    answer = run(name)
    assert answer["passed"] is False and answer["user_message"].startswith("The tests did not pass"), answer
    assert "the output reported" in answer["user_message"].lower()


# --- 4: the kept environment is checked against the lockfile, not only against a record ---------------------------

@pytest.mark.preview
@needs_uv
def test_a_forged_record_does_not_keep_an_environment_across_a_lock_change(signed_in, workspaces, turned_on, pids, steps,
                                                                            monkeypatch):
    """The new lockfile adds a package: a record the application rewrote says nothing changed."""
    from test_business_computer import ALLOWED, PACKAGE_LOCK, PACKAGE_PROJECT

    monkeypatch.setattr(preview.deps, "audit", lambda folder: dict(ALLOWED))
    name, ws = live_project(signed_in, pids)
    show(name)
    declared = settings.preview(gitops.project_files(name)["declaration"])
    (ws / "pyproject.toml").write_bytes(PACKAGE_PROJECT)
    new_lock = ws / "uv.lock"
    new_lock.write_bytes(PACKAGE_LOCK.replace("HOST", "files.pythonhosted.org").encode())
    forged = preview._environment_fingerprint(new_lock, (), preview._fingerprint(declared))
    preview._kept_file(name).write_text(json.dumps({"environment": forged}))  # as the application can
    gitops.save(name, "A new lockfile")
    steps.clear()
    assert show(name)["status"] == "ready"
    assert "installing" in steps


@pytest.mark.preview
@needs_uv
def test_an_environment_in_step_is_still_not_installed_again(signed_in, workspaces, turned_on, pids, steps):
    name, ws = live_project(signed_in, pids)
    show(name)
    steps.clear()
    change(name, ws, "app.py", LIVE + b"# a change to the code\n")
    assert show(name)["installed"] is False and "installing" not in steps


# --- 5: installers as modules -----------------------------------------------------------------------------------------

@pytest.mark.parametrize("module", ["uv", "pipx", "uv.__main__"])
@pytest.mark.parametrize("section", ["preview", "tests"])
def test_an_installer_is_not_a_module_to_run(module, section):
    run_line = f'["python", "-m", "{module}", "pip", "install", "x"'
    if section == "preview":
        text = f'[preview]\nsetup = [{run_line}]]\nrun = ["python", "app.py", "--host", "127.0.0.1", "--port", "{{port}}"]\n'
        assert "invalid" in settings.preview({"text": text})
    else:
        assert "invalid" in settings.tests({"text": f"[tests]\nrun = {run_line}]\n"})


# --- 6: what the programs' list reads -------------------------------------------------------------------------------

def link_folder(link: Path, target: Path) -> None:
    if WINDOWS:
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], check=True, capture_output=True)
    else:
        link.symlink_to(target, target_is_directory=True)


def test_the_programs_list_follows_no_link_out_of_the_environment(tmp_path):
    outside = tmp_path / "outside" / "evil-1.dist-info"
    outside.mkdir(parents=True)
    (outside / "entry_points.txt").write_text("[console_scripts]\nevil = x:y\n")
    environment = tmp_path / "environment" / "Lib" / "site-packages"
    real = environment / "good-1.dist-info"
    real.mkdir(parents=True)
    (real / "entry_points.txt").write_text("[console_scripts]\ngood = x:y\n")
    link_folder(environment / "linked", tmp_path / "outside")
    assert preview._console_scripts(tmp_path / "environment") == {"good"}


# --- 7: the hour is not given again --------------------------------------------------------------------------------

@pytest.mark.preview
@needs_uv
def test_a_fresh_start_of_the_same_version_keeps_the_hour(signed_in, workspaces, turned_on, pids):
    name, _ = live_project(signed_in, pids)
    show(name)
    deadline = preview._preview_state(preview._state_file(name))["deadline"]
    time.sleep(1.1)
    answer = tools.app_preview(name, fresh=True)
    while answer["status"] == "starting":
        time.sleep(0.2)
        answer = tools.app_preview(name)
    assert answer["status"] == "ready", answer
    assert preview._preview_state(preview._state_file(name))["deadline"] == pytest.approx(deadline, abs=1)


@pytest.mark.preview
@needs_uv
def test_a_silent_preview_started_again_keeps_the_hour(signed_in, workspaces, turned_on, pids, monkeypatch):
    name, _ = live_project(signed_in, pids)
    show(name)
    deadline = preview._preview_state(preview._state_file(name))["deadline"]
    time.sleep(1.1)
    monkeypatch.setattr(preview, "_still_answers", lambda port: False)
    answer = show(name)
    assert answer["ended_before"] == "silent", answer
    assert preview._preview_state(preview._state_file(name))["deadline"] == pytest.approx(deadline, abs=1)


# --- 8: a known limit ------------------------------------------------------------------------------------------------

def test_barriers_name_the_folders_windows_moves():
    text = " ".join((Path(preview.__file__).parents[3] / "docs" / "barriers.md").read_text(encoding="utf-8").split())
    assert "Known Folder Move" in text
