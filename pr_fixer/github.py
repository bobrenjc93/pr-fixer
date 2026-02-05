"""GitHub CLI wrapper for fetching PR data."""

import json
import re
import subprocess
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

from .models import PRComment, ReviewComment, InlineComment, CommentType, AllComments


@dataclass
class PRInfo:
    """Parsed information from a GitHub PR URL."""
    owner: str
    repo: str
    pr_number: int

    def __str__(self) -> str:
        return f"{self.owner}/{self.repo}#{self.pr_number}"

    @property
    def url(self) -> str:
        """Reconstruct the canonical PR URL."""
        return f"https://github.com/{self.owner}/{self.repo}/pull/{self.pr_number}"


class InvalidPRURLError(Exception):
    """Raised when a PR URL cannot be parsed."""
    pass


def parse_pr_url(url: str) -> PRInfo:
    """
    Parse a GitHub PR URL and extract owner, repo, and PR number.

    Supports various URL formats:
    - https://github.com/owner/repo/pull/123
    - https://github.com/owner/repo/pull/123/
    - https://github.com/owner/repo/pull/123/files
    - https://github.com/owner/repo/pull/123/commits
    - https://github.com/owner/repo/pull/123?query=param
    - https://github.com/owner/repo/pull/123#anchor
    - http://github.com/owner/repo/pull/123 (http variant)
    - github.com/owner/repo/pull/123 (without scheme)

    Args:
        url: A GitHub PR URL string

    Returns:
        PRInfo with owner, repo, and pr_number

    Raises:
        InvalidPRURLError: If the URL cannot be parsed as a valid GitHub PR URL
    """
    if not url or not isinstance(url, str):
        raise InvalidPRURLError("URL must be a non-empty string")

    # Clean up the URL
    url = url.strip()

    # Add scheme if missing
    if not url.startswith(('http://', 'https://')):
        if url.startswith('github.com'):
            url = 'https://' + url
        else:
            raise InvalidPRURLError(f"Invalid GitHub PR URL: {url}")

    # Parse the URL
    try:
        parsed = urlparse(url)
    except Exception as e:
        raise InvalidPRURLError(f"Failed to parse URL: {url}") from e

    # Validate host
    if parsed.netloc not in ('github.com', 'www.github.com'):
        raise InvalidPRURLError(
            f"URL must be from github.com, got: {parsed.netloc}"
        )

    # Parse the path: should be /{owner}/{repo}/pull/{number}[/...]
    path = parsed.path.strip('/')

    # Use regex to extract owner, repo, and PR number
    # Pattern: owner/repo/pull/number with optional additional path segments
    pattern = r'^([^/]+)/([^/]+)/pull/(\d+)(?:/.*)?$'
    match = re.match(pattern, path)

    if not match:
        raise InvalidPRURLError(
            f"URL path does not match expected format '{{owner}}/{{repo}}/pull/{{number}}': {parsed.path}"
        )

    owner = match.group(1)
    repo = match.group(2)
    pr_number_str = match.group(3)

    # Validate owner and repo names
    # GitHub usernames/repo names: alphanumeric, hyphens, underscores (no starting with hyphen for users)
    if not owner or not repo:
        raise InvalidPRURLError(f"Owner and repo must not be empty: {url}")

    # Convert PR number
    try:
        pr_number = int(pr_number_str)
    except ValueError:
        raise InvalidPRURLError(f"PR number must be a valid integer: {pr_number_str}")

    if pr_number <= 0:
        raise InvalidPRURLError(f"PR number must be positive: {pr_number}")

    return PRInfo(owner=owner, repo=repo, pr_number=pr_number)


class GitHubCLIError(Exception):
    """Raised when a GitHub CLI command fails."""
    pass


def fetch_discussion_comments(pr_info: PRInfo) -> list[PRComment]:
    """
    Fetch discussion comments from a GitHub PR using the gh CLI.

    Uses `gh pr view <number> --json comments` to retrieve general
    PR discussion comments (not inline code comments or review summaries).

    Args:
        pr_info: PRInfo object containing owner, repo, and pr_number

    Returns:
        List of PRComment objects representing discussion comments

    Raises:
        GitHubCLIError: If the gh CLI command fails
    """
    cmd = [
        "gh", "pr", "view", str(pr_info.pr_number),
        "--repo", f"{pr_info.owner}/{pr_info.repo}",
        "--json", "comments"
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True
        )
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.strip() if e.stderr else str(e)
        raise GitHubCLIError(
            f"Failed to fetch PR comments: {error_msg}"
        ) from e
    except FileNotFoundError:
        raise GitHubCLIError(
            "GitHub CLI (gh) not found. Please install it from https://cli.github.com/"
        )

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise GitHubCLIError(
            f"Failed to parse gh CLI output as JSON: {e}"
        ) from e

    comments = []
    for comment_data in data.get("comments", []):
        author = comment_data.get("author", {}).get("login", "unknown")
        body = comment_data.get("body", "")
        comments.append(PRComment(
            author=author,
            body=body,
            comment_type=CommentType.DISCUSSION
        ))

    return comments


def fetch_review_summaries(pr_info: PRInfo) -> list[ReviewComment]:
    """
    Fetch review summaries from a GitHub PR using the gh CLI.

    Uses `gh api repos/:owner/:repo/pulls/<number>/reviews` to retrieve
    review summaries (approve, request changes, or comments with body text).
    Only reviews with non-empty bodies are returned.

    Args:
        pr_info: PRInfo object containing owner, repo, and pr_number

    Returns:
        List of ReviewComment objects representing review summaries

    Raises:
        GitHubCLIError: If the gh CLI command fails
    """
    cmd = [
        "gh", "api",
        f"repos/{pr_info.owner}/{pr_info.repo}/pulls/{pr_info.pr_number}/reviews"
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True
        )
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.strip() if e.stderr else str(e)
        raise GitHubCLIError(
            f"Failed to fetch PR reviews: {error_msg}"
        ) from e
    except FileNotFoundError:
        raise GitHubCLIError(
            "GitHub CLI (gh) not found. Please install it from https://cli.github.com/"
        )

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise GitHubCLIError(
            f"Failed to parse gh CLI output as JSON: {e}"
        ) from e

    reviews = []
    for review_data in data:
        body = review_data.get("body", "")
        # Filter out reviews with empty bodies as per plan notes
        if not body or not body.strip():
            continue

        author = review_data.get("user", {}).get("login", "unknown")
        state = review_data.get("state", "UNKNOWN")
        reviews.append(ReviewComment(
            author=author,
            body=body,
            state=state
        ))

    return reviews


def fetch_inline_comments(pr_info: PRInfo) -> list[InlineComment]:
    """
    Fetch unresolved inline code comments from a GitHub PR using the GraphQL API.

    Uses the GraphQL API to retrieve inline code review comments along with
    their thread resolution status. Only comments from unresolved threads
    are returned.

    Args:
        pr_info: PRInfo object containing owner, repo, and pr_number

    Returns:
        List of InlineComment objects representing unresolved inline code comments

    Raises:
        GitHubCLIError: If the gh CLI command fails
    """
    graphql_query = """
query($owner: String!, $repo: String!, $number: Int!) {
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $number) {
      reviewThreads(first: 100) {
        nodes {
          isResolved
          comments(first: 100) {
            nodes {
              author { login }
              body
              path
              line
              originalLine
            }
          }
        }
      }
    }
  }
}
"""

    cmd = [
        "gh", "api", "graphql",
        "-f", f"query={graphql_query}",
        "-F", f"owner={pr_info.owner}",
        "-F", f"repo={pr_info.repo}",
        "-F", f"number={pr_info.pr_number}"
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True
        )
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.strip() if e.stderr else str(e)
        raise GitHubCLIError(
            f"Failed to fetch inline comments: {error_msg}"
        ) from e
    except FileNotFoundError:
        raise GitHubCLIError(
            "GitHub CLI (gh) not found. Please install it from https://cli.github.com/"
        )

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise GitHubCLIError(
            f"Failed to parse gh CLI output as JSON: {e}"
        ) from e

    inline_comments = []
    pr_data = data.get("data", {}).get("repository", {}).get("pullRequest", {})
    threads = pr_data.get("reviewThreads", {}).get("nodes", [])

    for thread in threads:
        if thread.get("isResolved", False):
            continue

        comments = thread.get("comments", {}).get("nodes", [])
        for comment_data in comments:
            author_data = comment_data.get("author")
            author = author_data.get("login", "unknown") if author_data else "unknown"
            body = comment_data.get("body", "")
            path = comment_data.get("path", "")
            line = comment_data.get("line")
            original_line = comment_data.get("originalLine")

            inline_comments.append(InlineComment(
                author=author,
                body=body,
                path=path,
                line=line,
                original_line=original_line
            ))

    return inline_comments


def fetch_all_comments(pr_info: PRInfo) -> AllComments:
    """
    Fetch all types of comments from a GitHub PR.

    This is a unified function that fetches:
    - Discussion comments (general PR conversation)
    - Review summaries (approve/request changes with body text)
    - Inline code comments (attached to specific lines)

    Args:
        pr_info: PRInfo object containing owner, repo, and pr_number

    Returns:
        AllComments object containing all comment types in a structured format

    Raises:
        GitHubCLIError: If any gh CLI command fails
    """
    discussion_comments = fetch_discussion_comments(pr_info)
    review_comments = fetch_review_summaries(pr_info)
    inline_comments = fetch_inline_comments(pr_info)

    return AllComments(
        discussion_comments=discussion_comments,
        review_comments=review_comments,
        inline_comments=inline_comments
    )
