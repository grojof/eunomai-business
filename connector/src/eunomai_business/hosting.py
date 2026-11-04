"""The git hosting's own API: what plain git cannot do, here pull requests and their reviews.

Cloning, fetching and pushing are git, the same on every hosting; sign-in is OAuth, set per provider. What differs is
each platform's API, so every call to it goes through one interface, `Hosting`, with one class per platform. Gitea
implements it. GitHub and GitLab are refused, by the build and when the connector starts, until each has its class
tested against a real server of its own: a connector that has no code for a platform never does half a proposal.
"""

import os
from urllib.parse import urlsplit

from . import auth

DEFAULT_PLATFORM = "gitea"
NOT_YET = {
    "github": "it needs a GitHub class for its REST API — pull requests, their reviews and review comments, and the "
              "repository's default branch — tested against a real GitHub",
    "gitlab": "it needs a GitLab class for its REST API v4 — merge requests, their approvals, notes and discussions, "
              "and the project's default branch — tested against a real GitLab",
}
"""Platforms an organization may name, refused until they work. `PLATFORMS` below holds the ones that do."""


class NotSupported(RuntimeError):
    """A platform this connector has no code for: said before anything is asked of the server."""


def platform_name() -> str:
    """The hosting platform the build named; Gitea when it named none, as every build before the setting existed."""
    return os.environ.get("EUNOMAI_PLATFORM", "").strip() or DEFAULT_PLATFORM


def refusal(name: str) -> str | None:
    """Why a platform cannot be used, or None when it can."""
    if name in PLATFORMS:
        return None
    if name in NOT_YET:
        return f"{name} is not supported yet: {NOT_YET[name]}"
    return f"{name!r} is not a hosting platform this connector knows: {', '.join(sorted([*PLATFORMS, *NOT_YET]))}"


class Hosting:
    """What the connector asks of the hosting, one method per operation, for one repository and one signed-in
    person. A new platform is one more class that implements every one."""

    OPERATIONS = ("find_proposal", "review", "open_proposal")

    def find_proposal(self, version: str) -> dict | None:
        """The latest pull request of a version: number, merged, state, the commit it proposed and its author.
        None when the hosting cannot tell."""
        raise NotImplementedError

    def review(self, number: int, author: str | None, head: str | None) -> dict | None:
        """What reviewers asked on an open pull request (`decision`, `complete`, `requests`). None when the hosting
        cannot tell."""
        raise NotImplementedError

    def open_proposal(self, version: str, title: str, body: str) -> dict:
        """Proposes the version for the default branch, or brings an open proposal's text up to date."""
        raise NotImplementedError


_REVIEW_TEXT, _COMMENT_TEXT, _CONVERSATION = 10_000, 2_000, 10


class Gitea(Hosting):
    """Gitea's REST API (`/api/v1`), with the person's own token."""

    def __init__(self, origin: str, token: str):
        parts = urlsplit(origin)
        segments = parts.path.strip("/").removesuffix(".git").split("/")
        prefix = "".join(f"/{s}" for s in segments[:-2])  # servers published under a sub-path
        self.api = f"{parts.scheme}://{parts.netloc}{prefix}/api/v1/repos/{segments[-2]}/{segments[-1]}"
        self.headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    def find_proposal(self, version: str) -> dict | None:
        mine = []
        try:
            with auth.http_client() as client:  # most recently updated first; a version's proposal is recent
                for page in range(1, 6):
                    response = client.get(f"{self.api}/pulls", headers=self.headers,
                                          params={"state": "all", "sort": "recentupdate", "limit": 50, "page": page})
                    if response.status_code != 200:
                        return None
                    batch = response.json()
                    mine += [p for p in batch if (p.get("head") or {}).get("ref") == version]
                    if mine or len(batch) < 50:
                        break
        except Exception:
            return None
        if not mine:
            return None
        latest = max(mine, key=lambda p: p.get("number", 0))
        return {"number": latest.get("number"), "merged": bool(latest.get("merged")), "state": latest.get("state"),
                "head": (latest.get("head") or {}).get("sha"), "author": (latest.get("user") or {}).get("login")}

    def review(self, number: int, author: str | None, head: str | None) -> dict | None:
        """`decision` comes from each reviewer's latest approval or request for changes (a later plain comment does
        not undo it): `changes_requested`, `updated_since_requests` (the version was sent again after them: waiting
        for a new review), `approved`, `comments` or `none`. `requests` holds each reviewer's latest note, the line
        comments not resolved and the last conversation comments, never the author's own. It is text from people
        with access to the repository: the specialist weighs it, never follows it as instructions. `complete` is
        false when part of it could not be read."""
        api, headers = self.api, self.headers

        def item(source: dict, text: str, limit: int, **more) -> dict:
            return {"by": (source.get("user") or {}).get("login"),
                    "at": source.get("submitted_at") or source.get("created_at"), "text": text[:limit],
                    **({"truncated": True} if len(text) > limit else {}), **more}

        def earlier(review: dict) -> bool:  # made on a version that has been sent again since
            return bool(review.get("stale") or (head and review.get("commit_id") and review["commit_id"] != head))

        def who(source: dict) -> str | None:
            return (source.get("user") or {}).get("login")

        complete, reviews, conversation = True, [], []
        with auth.http_client() as client:
            for page in range(1, 6):  # until an empty page: the server may hand out fewer than asked
                response = client.get(f"{api}/pulls/{number}/reviews", headers=headers,
                                      params={"page": page, "limit": 50})
                if response.status_code != 200:
                    return None
                if not response.json():
                    break
                reviews += response.json()
            else:
                complete = False
            talk = client.get(f"{api}/issues/{number}/comments", headers=headers)
            if talk.status_code == 200:
                conversation = talk.json()
            else:
                complete = False
            live = [r for r in sorted(reviews, key=lambda r: r.get("id") or 0)
                    if not r.get("dismissed") and r.get("state") in ("APPROVED", "COMMENT", "REQUEST_CHANGES")
                    and who(r) != author]
            deciding, latest, items = {}, {}, []
            for review in live:
                latest[who(review)] = review
                if review["state"] != "COMMENT":
                    deciding[who(review)] = review
            for review in latest.values():
                if (review.get("body") or "").strip():
                    items.append(item(review, review["body"], _REVIEW_TEXT, official=bool(review.get("official")),
                                      earlier_version=earlier(review)))
            for review in live:
                approval = deciding.get(who(review))
                if not review.get("comments_count") or (
                        approval and approval["state"] == "APPROVED"
                        and (review.get("id") or 0) < (approval.get("id") or 0)):
                    continue  # line comments the same reviewer approved afterwards are settled
                inline = client.get(f"{api}/pulls/{number}/reviews/{review['id']}/comments", headers=headers)
                if inline.status_code != 200:
                    complete = False
                    continue
                for comment in inline.json():
                    if comment.get("resolver") or who(comment) == author or not (comment.get("body") or "").strip():
                        continue
                    items.append(item(comment, comment["body"], _COMMENT_TEXT, official=bool(review.get("official")),
                                      earlier_version=earlier(review), file=comment.get("path"),
                                      line=comment.get("position") or comment.get("original_position")))
        conversation = [c for c in conversation if who(c) != author and (c.get("body") or "").strip()]
        items += [item(c, c["body"], _COMMENT_TEXT) for c in conversation[-_CONVERSATION:]]
        requested = [r for r in deciding.values() if r["state"] == "REQUEST_CHANGES"]
        decision = ("changes_requested" if any(not earlier(r) for r in requested)
                    else "updated_since_requests" if requested
                    else "approved" if deciding else "comments" if items else "none")
        return {"decision": decision, "complete": complete, "requests": sorted(items, key=lambda i: i["at"] or "")}

    def open_proposal(self, version: str, title: str, body: str) -> dict:
        with auth.http_client() as client:
            info = client.get(self.api, headers=self.headers)
            info.raise_for_status()
            base = info.json().get("default_branch") or "main"
            response = client.post(f"{self.api}/pulls", headers=self.headers,
                                   json={"head": version, "base": base, "title": title, "body": body})
        if response.status_code == 409:  # already open: the version just sent updates it; bring its text up to date
            existing = self.find_proposal(version)
            updated = False
            if existing and existing.get("state") == "open" and existing.get("number"):
                with auth.http_client() as client:
                    patched = client.patch(f"{self.api}/pulls/{existing['number']}", headers=self.headers,
                                           json={"title": title, "body": body})
                updated = patched.status_code in (200, 201)
            return {"created": False, "updated": updated, "base": base,
                    "reason": "a pull request for this version is already open"}
        if response.status_code != 201:
            raise RuntimeError(f"git server answered {response.status_code}: {response.text[:300]}")
        made = response.json()
        return {"created": True, "number": made.get("number"), "url": made.get("html_url"), "base": base}


PLATFORMS: dict[str, type[Hosting]] = {"gitea": Gitea}


def for_origin(origin: str, token: str) -> Hosting:
    """The hosting of a repository, for the person whose token this is. Refused for a platform with no code."""
    name = platform_name()
    why = refusal(name)
    if why:
        raise NotSupported(why)
    return PLATFORMS[name](origin, token)
