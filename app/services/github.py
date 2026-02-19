import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"


class GitHubService:
    """Fetches comprehensive GitHub profile data using a personal access token."""

    def __init__(self, token: str):
        self.token = token
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def fetch_comprehensive_profile(self) -> dict[str, Any]:
        """Fetch complete GitHub profile including repos, commits, and languages."""
        async with httpx.AsyncClient(
            base_url=GITHUB_API_BASE,
            headers=self.headers,
            timeout=30.0,
        ) as client:
            # Fetch all data concurrently where possible
            user = await self._fetch_user(client)
            username = user.get("login", "")

            repos = await self._fetch_repos(client)
            pinned = await self._fetch_pinned_repos(client, username)
            languages = self._aggregate_languages(repos)
            recent_commits = await self._fetch_recent_commits(client, username, repos)
            contribution_stats = await self._fetch_contribution_stats(client, username)

            return {
                "profile": {
                    "username": username,
                    "name": user.get("name", ""),
                    "bio": user.get("bio", ""),
                    "company": user.get("company", ""),
                    "location": user.get("location", ""),
                    "blog": user.get("blog", ""),
                    "public_repos": user.get("public_repos", 0),
                    "followers": user.get("followers", 0),
                    "following": user.get("following", 0),
                    "html_url": user.get("html_url", ""),
                    "created_at": user.get("created_at", ""),
                },
                "repositories": [
                    {
                        "name": r.get("name", ""),
                        "description": r.get("description", ""),
                        "language": r.get("language", ""),
                        "stargazers_count": r.get("stargazers_count", 0),
                        "forks_count": r.get("forks_count", 0),
                        "topics": r.get("topics", []),
                        "html_url": r.get("html_url", ""),
                        "created_at": r.get("created_at", ""),
                        "updated_at": r.get("updated_at", ""),
                        "fork": r.get("fork", False),
                    }
                    for r in repos
                ],
                "pinned_repos": pinned,
                "languages": languages,
                "recent_commits": recent_commits,
                "contribution_stats": contribution_stats,
            }

    async def _fetch_user(self, client: httpx.AsyncClient) -> dict:
        """Fetch authenticated user profile."""
        resp = await client.get("/user")
        resp.raise_for_status()
        return resp.json()

    async def _fetch_repos(self, client: httpx.AsyncClient) -> list[dict]:
        """Fetch all repositories (paginated), sorted by most recently updated."""
        repos = []
        page = 1
        per_page = 100
        while True:
            resp = await client.get(
                "/user/repos",
                params={
                    "sort": "updated",
                    "direction": "desc",
                    "per_page": per_page,
                    "page": page,
                    "type": "owner",
                },
            )
            resp.raise_for_status()
            batch = resp.json()
            if not batch:
                break
            repos.extend(batch)
            if len(batch) < per_page:
                break
            page += 1
        return repos

    async def _fetch_pinned_repos(
        self, client: httpx.AsyncClient, username: str
    ) -> list[dict]:
        """Fetch pinned repositories via GitHub GraphQL API."""
        query = """
        query($username: String!) {
          user(login: $username) {
            pinnedItems(first: 6, types: REPOSITORY) {
              nodes {
                ... on Repository {
                  name
                  description
                  url
                  stargazerCount
                  primaryLanguage { name }
                  repositoryTopics(first: 10) {
                    nodes { topic { name } }
                  }
                }
              }
            }
          }
        }
        """
        try:
            resp = await client.post(
                "https://api.github.com/graphql",
                json={"query": query, "variables": {"username": username}},
            )
            resp.raise_for_status()
            data = resp.json()
            nodes = (
                data.get("data", {})
                .get("user", {})
                .get("pinnedItems", {})
                .get("nodes", [])
            )
            return [
                {
                    "name": n.get("name", ""),
                    "description": n.get("description", ""),
                    "url": n.get("url", ""),
                    "stars": n.get("stargazerCount", 0),
                    "language": (n.get("primaryLanguage") or {}).get("name", ""),
                    "topics": [
                        t["topic"]["name"]
                        for t in n.get("repositoryTopics", {}).get("nodes", [])
                    ],
                }
                for n in nodes
            ]
        except Exception as e:
            logger.warning(f"Failed to fetch pinned repos: {e}")
            return []

    def _aggregate_languages(self, repos: list[dict]) -> dict[str, int]:
        """Count repos per language."""
        lang_counts: dict[str, int] = {}
        for r in repos:
            lang = r.get("language")
            if lang:
                lang_counts[lang] = lang_counts.get(lang, 0) + 1
        # Sort by count descending
        return dict(sorted(lang_counts.items(), key=lambda x: x[1], reverse=True))

    async def _fetch_recent_commits(
        self,
        client: httpx.AsyncClient,
        username: str,
        repos: list[dict],
    ) -> list[dict]:
        """Fetch recent commits from the top 10 most recently updated repos."""
        commits = []
        # Only check top 10 repos to avoid rate limits
        top_repos = [r for r in repos if not r.get("fork", False)][:10]

        for repo in top_repos:
            repo_name = repo.get("full_name", "")
            if not repo_name:
                continue
            try:
                resp = await client.get(
                    f"/repos/{repo_name}/commits",
                    params={
                        "author": username,
                        "per_page": 5,
                    },
                )
                if resp.status_code != 200:
                    continue
                repo_commits = resp.json()
                for c in repo_commits:
                    commit_data = c.get("commit", {})
                    commits.append(
                        {
                            "repo": repo.get("name", ""),
                            "message": commit_data.get("message", "").split("\n")[0],
                            "date": commit_data.get("author", {}).get("date", ""),
                            "sha": c.get("sha", "")[:7],
                        }
                    )
            except Exception as e:
                logger.warning(f"Failed to fetch commits for {repo_name}: {e}")
                continue

        # Sort by date descending and limit
        commits.sort(key=lambda x: x.get("date", ""), reverse=True)
        return commits[:30]

    async def _fetch_contribution_stats(
        self, client: httpx.AsyncClient, username: str
    ) -> dict:
        """Fetch contribution statistics via the events API."""
        try:
            resp = await client.get(
                f"/users/{username}/events",
                params={"per_page": 100},
            )
            if resp.status_code != 200:
                return {}

            events = resp.json()
            push_events = [e for e in events if e.get("type") == "PushEvent"]
            pr_events = [e for e in events if e.get("type") == "PullRequestEvent"]
            issue_events = [e for e in events if e.get("type") == "IssuesEvent"]
            create_events = [e for e in events if e.get("type") == "CreateEvent"]

            total_commits_recent = sum(
                len(e.get("payload", {}).get("commits", [])) for e in push_events
            )

            return {
                "recent_push_events": len(push_events),
                "recent_pr_events": len(pr_events),
                "recent_issue_events": len(issue_events),
                "recent_create_events": len(create_events),
                "recent_commits_count": total_commits_recent,
                "total_events_sampled": len(events),
            }
        except Exception as e:
            logger.warning(f"Failed to fetch contribution stats: {e}")
            return {}
