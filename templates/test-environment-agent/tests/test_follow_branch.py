"""follow-branch.sh against a local repository: standard library only, so it runs on any Linux with git and flock
(python3 -m unittest discover -s tests), and under pytest in CI."""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "follow-branch.sh"
LINUX = sys.platform.startswith("linux") and all(shutil.which(tool) for tool in ("bash", "git", "flock", "tar",
                                                                                 "timeout"))
GIT_ENV = {"GIT_AUTHOR_NAME": "IT", "GIT_AUTHOR_EMAIL": "it@example.test", "GIT_COMMITTER_NAME": "IT",
           "GIT_COMMITTER_EMAIL": "it@example.test", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"}


@unittest.skipUnless(LINUX, "needs Linux with bash, git, flock, tar and timeout")
class FollowBranch(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="follow-branch-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.origin = self.tmp / "origin"
        self.git("init", "-q", "-b", "main", str(self.origin), cwd=self.tmp)
        self.commit("app.py", "print('one')\n")
        self.git("branch", "pruebas")
        self.state = self.tmp / "state"
        self.applied = self.tmp / "applied.log"
        self.apply = self.tmp / "it" / "apply.sh"
        self.apply.parent.mkdir()
        self.write_apply("exit 0")

    def git(self, *args, cwd=None):
        return subprocess.run(["git", *args], cwd=cwd or self.origin, env={**os.environ, **GIT_ENV}, check=True,
                              capture_output=True, text=True).stdout.strip()

    def commit(self, name: str, text: str, branch: str = "main") -> str:
        if self.git("symbolic-ref", "--short", "HEAD") != branch:  # a new repository has no commit to check out
            self.git("checkout", "-q", branch)
        (self.origin / name).parent.mkdir(parents=True, exist_ok=True)
        (self.origin / name).write_text(text)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", f"change {name}")
        return self.git("rev-parse", "HEAD")

    def write_apply(self, body: str):
        self.apply.write_text(f'#!/usr/bin/env bash\necho "$1 $2" >> "{self.applied}"\n{body}\n')
        self.apply.chmod(0o755)

    def run_agent(self, state=None, **overrides) -> subprocess.CompletedProcess:
        env = {"PATH": os.environ["PATH"], "REPOSITORY": f"file://{self.origin}", "BRANCH": "pruebas",
               "APPLY": str(self.apply), **overrides}
        return subprocess.run(["bash", str(SCRIPT), str(state or self.state)], env=env, capture_output=True,
                              text=True)

    def applied_commits(self) -> list[str]:
        return [line.split()[1] for line in self.applied.read_text().splitlines()] if self.applied.exists() else []

    def deployed(self) -> str:
        return (self.state / "deployed").read_text().strip()

    def move_branch(self, name: str, text: str) -> str:
        commit = self.commit(name, text)
        self.git("branch", "-f", "pruebas", commit)
        return commit

    def test_a_new_commit_becomes_the_current_release(self):
        head = self.git("rev-parse", "pruebas")
        done = self.run_agent()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.deployed(), head)
        current = self.state / "current"
        self.assertEqual(Path(os.readlink(current)), self.state / "releases" / head)
        self.assertEqual((current / "app.py").read_text(), "print('one')\n")
        self.assertFalse((current / ".git").exists())  # files only: no history, no hooks
        self.assertEqual(self.applied_commits(), [head])
        self.assertEqual(sorted(p.name for p in self.state.iterdir()), ["current", "deployed", "lock", "releases"])

    def test_nothing_new_applies_nothing(self):
        self.run_agent()
        self.assertEqual(self.run_agent().returncode, 0)
        self.assertEqual(len(self.applied_commits()), 1)

    def test_a_branch_replaced_by_a_new_version_is_followed(self):
        self.run_agent()
        replaced = self.move_branch("app.py", "print('two')\n")
        self.git("checkout", "-q", "--orphan", "other")  # an unrelated history replaces it next
        unrelated = self.commit("other.py", "x = 1\n", branch="other")
        self.assertEqual(self.run_agent().returncode, 0)
        self.assertEqual(self.deployed(), replaced)
        self.git("branch", "-f", "pruebas", unrelated)
        self.assertEqual(self.run_agent().returncode, 0)
        self.assertEqual(self.deployed(), unrelated)

    def test_apply_gets_neither_the_key_nor_the_repositorys_address(self):
        self.write_apply(f'env > "{self.tmp}/apply.env"')
        self.assertEqual(self.run_agent(SSH_KEY="", CREDENTIALS_DIRECTORY="/nowhere").returncode, 0)
        seen = (self.tmp / "apply.env").read_text()
        for name in ("REPOSITORY=", "SSH_KEY=", "GIT_SSH_COMMAND=", "CREDENTIALS_DIRECTORY="):
            self.assertNotIn(name, seen)

    def test_what_the_branchs_code_leaves_does_not_change_the_next_fetch(self):
        # the branch's code, run by APPLY, writes where a kept git copy would be, and a git configuration
        self.write_apply('mkdir -p "$1/../../mirror.git/hooks" && echo "[url \\"file:///evil/\\"] insteadOf = /" '
                         '> "$1/../../mirror.git/config"')
        self.run_agent()
        honest = self.move_branch("app.py", "print('two')\n")
        self.assertEqual(self.run_agent().returncode, 0)
        self.assertEqual(self.deployed(), honest)

    def test_a_failed_apply_keeps_the_last_release_and_is_not_retried(self):
        self.run_agent()
        good = self.deployed()
        self.write_apply("exit 1")
        bad = self.move_branch("app.py", "broken\n")
        failed = self.run_agent()
        self.assertEqual(failed.returncode, 2)
        self.assertIn("previous release stays current", failed.stderr)
        self.assertEqual(self.deployed(), good)
        self.assertEqual((self.state / "current" / "app.py").read_text(), "print('one')\n")
        self.assertFalse((self.state / "releases" / bad).exists())
        skipped = self.run_agent()  # the same commit is not tried again, and the log says how to retry it...
        self.assertEqual(skipped.returncode, 0)
        self.assertIn("remove", skipped.stdout)
        self.assertEqual(self.applied_commits().count(bad), 1)
        self.write_apply("exit 0")
        fixed = self.move_branch("app.py", "print('three')\n")  # ...until the branch moves
        self.assertEqual(self.run_agent().returncode, 0)
        self.assertEqual(self.deployed(), fixed)
        self.assertFalse((self.state / "failed").exists())

    def test_an_apply_that_hangs_counts_as_failed(self):
        self.write_apply("sleep 30")
        done = self.run_agent(APPLY_TIMEOUT="1")
        self.assertEqual(done.returncode, 2)
        self.assertEqual((self.state / "failed").read_text().strip(), self.git("rev-parse", "pruebas"))

    def test_a_run_stopped_after_switching_does_not_apply_again(self):
        self.run_agent()
        (self.state / "deployed").unlink()  # stopped between making it current and recording it
        self.assertEqual(self.run_agent().returncode, 0)
        self.assertEqual(len(self.applied_commits()), 1)
        self.assertEqual(self.deployed(), self.git("rev-parse", "pruebas"))

    def test_only_the_newest_releases_are_kept(self):
        for number in range(4):
            self.move_branch("app.py", f"print({number})\n")
            self.assertEqual(self.run_agent(KEEP="2").returncode, 0)
        releases = sorted(p.name for p in (self.state / "releases").iterdir())
        self.assertEqual(len(releases), 2)
        self.assertIn(self.deployed(), releases)

    def test_a_run_already_applying_is_left_alone(self):
        self.state.mkdir()
        (self.state / "lock").touch()
        holder = subprocess.Popen(["flock", "-x", str(self.state / "lock"), "sleep", "5"])
        self.addCleanup(lambda: (holder.kill(), holder.wait()))
        subprocess.run(["sleep", "0.5"])
        done = self.run_agent()
        self.assertEqual(done.returncode, 0)
        self.assertEqual(self.applied_commits(), [])

    def test_settings_it_cannot_have_meant_stop_before_anything_runs(self):
        cases = [{"BRANCH": "../main"}, {"BRANCH": "a/.b"}, {"BRANCH": "x.lock"}, {"BRANCH": "-x"},
                 {"APPLY": "apply.sh"}, {"APPLY": str(self.state / "apply.sh")}, {"state": "state"},
                 {"KEEP": "0"}, {"APPLY_TIMEOUT": "x"}, {"REPOSITORY": "--upload-pack=touch /tmp/x"},
                 {"REPOSITORY": "https://token@git.example.test/r.git"}, {"REPOSITORY": "ext::sh -c x"},
                 {"SSH_KEY": str(self.apply)}, {"SSH_KEY": "/etc/key'x", "KNOWN_HOSTS": "/etc/hosts"}]
        for overrides in cases:
            with self.subTest(**overrides):
                done = self.run_agent(**overrides)
                self.assertEqual(done.returncode, 2, done.stderr)
                self.assertEqual(self.applied_commits(), [])

    def test_the_servers_and_users_git_configuration_is_ignored(self):
        home = self.tmp / "home"
        home.mkdir()
        (home / ".gitconfig").write_text('[url "file:///nowhere/"]\n\tinsteadOf = file:///\n')
        done = self.run_agent(HOME=str(home))
        self.assertEqual(done.returncode, 0, done.stderr)


if __name__ == "__main__":
    unittest.main()
