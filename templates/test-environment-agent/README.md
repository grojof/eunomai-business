# Branch-following agent for Linux servers

Runs on the server it deploys to and **pulls** one branch: each new commit is fetched, unpacked as a release and
applied by IT's own command. A test environment follows the project's test branch (the one `version_to_test`
updates); production can follow `main` the same way. The application's credentials stay on that server: the git
server holds none. Why pulling: [project practices](../../docs/project-practices.md#a-test-environment-without-waiting-for-it).

Needs bash, git, flock, tar, `timeout` and systemd, and a git server with read-only deploy keys over SSH (GitHub,
Gitea, GitLab...). It is independent of how the application signs users in.

| File | What it is |
|---|---|
| `follow-branch.sh` | The agent |
| `follow-branch@.service`, `follow-branch@.timer` | One instance per application, every minute, as that application's own unprivileged user |
| `restart-on-deploy@.path`, `restart-on-deploy@.service` | Restart the application when a release becomes current |
| `example.env` | The instance's settings |
| `apply.example.sh` | Example of IT's apply command (Python with uv and Alembic) |

## Install it for one application (`example-project`)

As root, on the server:

```sh
# Once per server
install -d -m 0755 /usr/local/lib/follow-branch /etc/follow-branch
install -m 0755 follow-branch.sh /usr/local/lib/follow-branch/
install -m 0644 follow-branch@.service follow-branch@.timer restart-on-deploy@.path restart-on-deploy@.service \
    /etc/systemd/system/
ssh-keyscan -p 22 git.example.internal > /etc/follow-branch/known_hosts  # check the fingerprints with the server's
chmod 0600 /etc/follow-branch/known_hosts

# Per application
useradd --system --no-create-home --shell /usr/sbin/nologin fb-example-project
ssh-keygen -t ed25519 -N '' -C fb-example-project -f /etc/follow-branch/example-project.key
chmod 0600 /etc/follow-branch/example-project.key   # add the .pub to the repository as a read-only deploy key
install -m 0600 example.env /etc/follow-branch/example-project.env                     # and edit it
install -m 0755 apply.example.sh /usr/local/lib/follow-branch/apply-example-project.sh  # and adapt it

systemctl daemon-reload
systemctl enable --now follow-branch@example-project.timer restart-on-deploy@example-project.path
journalctl -u follow-branch@example-project -f
```

The application runs from `/var/lib/follow-branch/example-project/current` as a user in the group
`fb-example-project`; start it once the first release is current, and each new release restarts it. Tools APPLY
uses (uv, for example) are installed for the whole system, and its configuration is readable by
`fb-example-project`.

## What it guarantees

| Risk | How it is handled |
|---|---|
| Someone with access to the git server reaching the server | The server only reads, over SSH with a read-only key and known host keys; nothing connects to it |
| Code from the branch changing later fetches | Each commit is fetched into a throwaway repository and unpacked as files only (no `.git`, hooks or submodules); no git configuration of the server or user applies |
| Code from the branch reading the deploy key | APPLY runs without the key or the repository's address in its environment |
| One application reading another's key, settings or releases | One user per application; settings and keys readable by root only, handed over by systemd |
| The branch's code acting on the system | No privileges and no way to gain them, system read-only, no home folders, writes only to its state folder (checked on Ubuntu 24.04) |
| A failing or hung apply | The previous release stays live; that commit is not tried again until the branch moves (remove `<state>/failed` to retry). What APPLY changed before failing, such as a migration, stays changed |

It does not make the branch's code trustworthy: on a test environment that code is unreviewed, so the server stays
apart from production, with test data and test credentials only. Large files in Git LFS arrive as pointers.
