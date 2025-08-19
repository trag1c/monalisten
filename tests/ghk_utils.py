from typing import cast

from githubkit.versions.v2022_11_28.models import Repository, SimpleUser
from githubkit.webhooks import sign as ghk_sign

EX_URL = "https://example.com"

DUMMY_USER = SimpleUser(
    login="dummy",
    id=0,
    node_id="0",
    gravatar_id=None,
    url=EX_URL,
    type="User",
    site_admin=False,
    **dict.fromkeys(
        (
            f"{kind}_url" for kind in (
                "avatar", "html", "followers", "following", "gists", "starred",
                "subscriptions", "organizations", "repos", "events", "received_events",
            )
        ),
        EX_URL,
    ),
).model_dump(mode="json")  # fmt: skip

DUMMY_REPO = Repository(
    id=0,
    node_id="0",
    name="foo",
    full_name="dummy/foo",
    license=None,
    forks=0,
    owner=cast("SimpleUser", DUMMY_USER),
    description=None,
    fork=False,
    url=EX_URL,
    homepage=None,
    language=None,
    forks_count=0,
    stargazers_count=0,
    watchers_count=0,
    size=0,
    default_branch="main",
    open_issues_count=0,
    has_pages=False,
    disabled=False,
    pushed_at=None,
    created_at=None,
    updated_at=None,
    open_issues=0,
    watchers=0,
    **dict.fromkeys(  # pyright: ignore [reportArgumentType]
        (
            f"{kind}_url" for kind in (
                "html", "archive", "assignees", "blobs", "branches", "collaborators",
                "comments", "commits", "compare", "contents", "contributors",
                "deployments", "downloads", "events", "forks",
                "git_commits", "git_refs", "git_tags", "git", "issue_comment",
                "issue_events", "issues", "keys", "labels", "languages", "merges",
                "milestones", "notifications", "pulls", "releases", "ssh", "stargazers",
                "statuses", "subscribers", "subscription", "tags", "teams", "trees",
                "clone", "mirror", "hooks", "svn",
            )
        ),
        EX_URL,
    ),
).model_dump(mode="json", exclude_unset=True)  # fmt: skip

DUMMY_AUTH_EVENT = {
    "X-GitHub-Event": "github_app_authorization",
    "body": {"action": "revoked", "sender": DUMMY_USER},
}

DUMMY_STAR_EVENT = {
    "X-GitHub-Event": "star",
    "body": {
        "action": "created",
        "repository": DUMMY_REPO,
        "sender": DUMMY_USER,
        "starred_at": "2025-08-14T00:00:00Z",
    },
}


def sign_auth_event(secret: str) -> str:
    return ghk_sign(secret, DUMMY_AUTH_EVENT["body"])
