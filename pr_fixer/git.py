"""Git operations for PR Fixer."""

import json
import re
import shutil
import subprocess
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .github import PRInfo


def is_ghstack_pr(branch_name: str) -> bool:
    """
    Detect if a PR is using ghstack based on its branch name.

    ghstack PRs have branch names matching the pattern:
    - gh/<username>/<number>/head
    - gh/<username>/<number>/base
    - gh/<username>/<number>/orig

    Args:
        branch_name: The branch name to check

    Returns:
        True if this appears to be a ghstack branch, False otherwise
    """
    # Pattern: gh/<username>/<number>/<suffix>
    # where suffix is typically 'head', 'base', or 'orig'
    pattern = r'^gh/[^/]+/\d+/(head|base|orig)$'
    return bool(re.match(pattern, branch_name))


def check_ghstack_available() -> bool:
    """
    Check if ghstack is installed and available.

    Returns:
        True if ghstack is available, False otherwise
    """
    return shutil.which("ghstack") is not None


class GhstackError(Exception):
    """Raised when a ghstack operation fails."""
    pass


def checkout_ghstack_pr(pr_url: str, cwd: str | None = None) -> None:
    """
    Checkout a PR using ghstack.

    This runs `ghstack checkout <pr_url>` to checkout the PR branch.

    Args:
        pr_url: The full GitHub PR URL
        cwd: Working directory to run the command in (defaults to current directory)

    Raises:
        GhstackError: If ghstack is not installed or the checkout fails
    """
    if not check_ghstack_available():
        raise GhstackError(
            "ghstack is not installed. Install it with: pip install ghstack\n"
            "See https://github.com/ezyang/ghstack for details."
        )

    cmd = ["ghstack", "checkout", pr_url]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            cwd=cwd
        )
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.strip() if e.stderr else str(e)
        raise GhstackError(
            f"Failed to checkout PR with ghstack: {error_msg}"
        ) from e
    except FileNotFoundError:
        raise GhstackError(
            "ghstack not found. Please install it with: pip install ghstack"
        )


class GitError(Exception):
    """Raised when a git operation fails."""
    pass


class GitHubCLIError(Exception):
    """Raised when a GitHub CLI command fails."""
    pass


def get_pr_branch_name(pr_info: "PRInfo") -> str:
    """
    Get the branch name for a GitHub PR using the gh CLI.

    Uses `gh pr view <number> --json headRefName` to retrieve the
    branch name that the PR is proposing to merge.

    Args:
        pr_info: PRInfo object containing owner, repo, and pr_number

    Returns:
        The branch name as a string (e.g., "feature/my-branch")

    Raises:
        GitHubCLIError: If the gh CLI command fails
    """
    cmd = [
        "gh", "pr", "view", str(pr_info.pr_number),
        "--repo", f"{pr_info.owner}/{pr_info.repo}",
        "--json", "headRefName"
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
            f"Failed to get PR branch name: {error_msg}"
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

    branch_name = data.get("headRefName")
    if not branch_name:
        raise GitHubCLIError(
            f"No branch name found for PR {pr_info.pr_number}"
        )

    return branch_name


def checkout_pr_branch(branch_name: str, cwd: str | None = None) -> None:
    """
    Checkout the specified branch for a PR.

    This function handles the case where the branch may not exist locally
    by first fetching from the remote. It attempts to checkout the branch,
    and if that fails, fetches and tries again.

    Args:
        branch_name: The branch name to checkout (e.g., "feature/my-branch")
        cwd: Working directory to run git commands in (defaults to current directory)

    Raises:
        GitError: If the checkout operation fails
    """
    # First, try a simple checkout in case the branch already exists locally
    checkout_cmd = ["git", "checkout", branch_name]

    result = subprocess.run(
        checkout_cmd,
        capture_output=True,
        text=True,
        cwd=cwd
    )

    if result.returncode == 0:
        # Successfully checked out the branch
        return

    # Branch doesn't exist locally, try to checkout from remote tracking branch
    # This handles the case where the remote tracking branch already exists
    checkout_track_cmd = ["git", "checkout", "-b", branch_name, f"origin/{branch_name}"]
    result = subprocess.run(
        checkout_track_cmd,
        capture_output=True,
        text=True,
        cwd=cwd
    )

    if result.returncode == 0:
        return

    # Remote tracking branch doesn't exist, need to fetch first
    fetch_cmd = ["git", "fetch", "origin", f"{branch_name}:{branch_name}"]

    try:
        result = subprocess.run(
            fetch_cmd,
            capture_output=True,
            text=True,
            check=True,
            cwd=cwd
        )
        # Fetch with branch creation succeeded, now checkout
        try:
            subprocess.run(
                checkout_cmd,
                capture_output=True,
                text=True,
                check=True,
                cwd=cwd
            )
            return
        except subprocess.CalledProcessError as e:
            error_msg = e.stderr.strip() if e.stderr else str(e)
            raise GitError(
                f"Failed to checkout branch '{branch_name}': {error_msg}"
            ) from e
    except subprocess.CalledProcessError:
        # If fetching with branch creation fails, try a simple fetch
        # then checkout with tracking
        simple_fetch_cmd = ["git", "fetch", "origin", branch_name]
        try:
            subprocess.run(
                simple_fetch_cmd,
                capture_output=True,
                text=True,
                check=True,
                cwd=cwd
            )
        except subprocess.CalledProcessError as e:
            error_msg = e.stderr.strip() if e.stderr else str(e)
            raise GitError(
                f"Failed to fetch branch '{branch_name}' from remote: {error_msg}"
            ) from e
        except FileNotFoundError:
            raise GitError(
                "git not found. Please ensure git is installed and in your PATH."
            )

        # Try to checkout with tracking
        checkout_track_cmd = ["git", "checkout", "-b", branch_name, f"origin/{branch_name}"]
        try:
            subprocess.run(
                checkout_track_cmd,
                capture_output=True,
                text=True,
                check=True,
                cwd=cwd
            )
            return
        except subprocess.CalledProcessError as e:
            error_msg = e.stderr.strip() if e.stderr else str(e)
            raise GitError(
                f"Failed to checkout branch '{branch_name}': {error_msg}"
            ) from e
    except FileNotFoundError:
        raise GitError(
            "git not found. Please ensure git is installed and in your PATH."
        )



class RepositoryMismatchError(Exception):
    """Raised when the current repository doesn't match the PR's repository."""
    pass


def validate_repository(pr_info: "PRInfo", cwd: str | None = None) -> None:
    """
    Validate that the current working directory is the correct repository for the PR.

    Compares the current git repository's remote URL(s) with the expected
    owner/repo from the PR. Checks both 'origin' remote and other remotes.

    Args:
        pr_info: PRInfo object containing owner and repo to validate against
        cwd: Working directory to run git commands in (defaults to current directory)

    Raises:
        RepositoryMismatchError: If the current repo doesn't match the PR's repo
        GitError: If we can't determine the current repository info
    """
    # Get all remotes and their URLs
    cmd = ["git", "remote", "-v"]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            cwd=cwd
        )
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.strip() if e.stderr else str(e)
        raise GitError(
            f"Failed to get git remotes: {error_msg}. "
            "Are you running this from within a git repository?"
        ) from e
    except FileNotFoundError:
        raise GitError(
            "git not found. Please ensure git is installed and in your PATH."
        )

    if not result.stdout.strip():
        raise GitError(
            "No git remotes found. Is this a git repository with remotes configured?"
        )

    # Parse remote URLs to extract owner/repo
    # Supports both SSH and HTTPS URLs:
    # - https://github.com/owner/repo.git
    # - https://github.com/owner/repo
    # - git@github.com:owner/repo.git
    # - git@github.com:owner/repo
    # - ssh://git@github.com/owner/repo.git

    expected_owner = pr_info.owner.lower()
    expected_repo = pr_info.repo.lower()

    # Patterns to extract owner/repo from various URL formats
    patterns = [
        # HTTPS: https://github.com/owner/repo(.git)
        r'https?://github\.com/([^/]+)/([^/\s]+?)(?:\.git)?(?:\s|$)',
        # SSH: git@github.com:owner/repo(.git)
        r'git@github\.com:([^/]+)/([^/\s]+?)(?:\.git)?(?:\s|$)',
        # SSH with protocol: ssh://git@github.com/owner/repo(.git)
        r'ssh://git@github\.com/([^/]+)/([^/\s]+?)(?:\.git)?(?:\s|$)',
    ]

    found_repos = set()
    for line in result.stdout.strip().split('\n'):
        for pattern in patterns:
            match = re.search(pattern, line)
            if match:
                found_owner = match.group(1).lower()
                found_repo = match.group(2).lower()
                found_repos.add((found_owner, found_repo))

                if found_owner == expected_owner and found_repo == expected_repo:
                    # Found a matching remote
                    return

    if not found_repos:
        raise GitError(
            "Could not parse any GitHub remote URLs from this repository. "
            "Expected format: https://github.com/owner/repo or git@github.com:owner/repo"
        )

    # Build a helpful error message with the found repos
    found_repos_list = [f"{owner}/{repo}" for owner, repo in sorted(found_repos)]
    found_repos_str = ", ".join(found_repos_list)

    raise RepositoryMismatchError(
        f"Repository mismatch: This PR is from '{pr_info.owner}/{pr_info.repo}' "
        f"but the current repository has remote(s) pointing to: {found_repos_str}. "
        f"Please run this command from the correct repository directory."
    )


def get_current_branch(cwd: str | None = None) -> str:
    """
    Get the name of the currently checked out branch.

    Args:
        cwd: Working directory to run git commands in (defaults to current directory)

    Returns:
        The current branch name as a string

    Raises:
        GitError: If the git command fails
    """
    cmd = ["git", "branch", "--show-current"]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            cwd=cwd
        )
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.strip() if e.stderr else str(e)
        raise GitError(
            f"Failed to get current branch: {error_msg}"
        ) from e
    except FileNotFoundError:
        raise GitError(
            "git not found. Please ensure git is installed and in your PATH."
        )

    return result.stdout.strip()


class UncommittedChangesError(Exception):
    """Raised when there are uncommitted changes that would be lost."""
    pass


def check_uncommitted_changes(cwd: str | None = None) -> tuple[bool, list[str]]:
    """
    Check if there are uncommitted changes in the working directory.

    Args:
        cwd: Working directory to run git commands in (defaults to current directory)

    Returns:
        Tuple of (has_changes, list_of_changed_files)

    Raises:
        GitError: If the git command fails
    """
    cmd = ["git", "status", "--porcelain"]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            cwd=cwd
        )
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.strip() if e.stderr else str(e)
        raise GitError(
            f"Failed to check git status: {error_msg}"
        ) from e
    except FileNotFoundError:
        raise GitError(
            "git not found. Please ensure git is installed and in your PATH."
        )

    output = result.stdout.strip()
    if not output:
        return False, []

    # Parse the output to get list of changed files
    changed_files = []
    for line in output.split('\n'):
        if line.strip():
            # Format is XY filename, where XY is the status
            # We want just the filename part
            parts = line.split(maxsplit=1)
            if len(parts) >= 2:
                changed_files.append(parts[1])
            else:
                changed_files.append(line.strip())

    return True, changed_files


def require_clean_working_directory(cwd: str | None = None) -> None:
    """
    Require that the working directory has no uncommitted changes.

    Args:
        cwd: Working directory to run git commands in (defaults to current directory)

    Raises:
        UncommittedChangesError: If there are uncommitted changes
        GitError: If the git command fails
    """
    has_changes, changed_files = check_uncommitted_changes(cwd=cwd)
    if has_changes:
        files_preview = changed_files[:5]
        if len(changed_files) > 5:
            files_str = "\n  ".join(files_preview) + f"\n  ... and {len(changed_files) - 5} more"
        else:
            files_str = "\n  ".join(files_preview)

        raise UncommittedChangesError(
            f"You have uncommitted changes that would be lost during checkout:\n  {files_str}\n\n"
            "Please commit or stash your changes first:\n"
            "  git stash        # to temporarily save changes\n"
            "  git stash pop    # to restore changes later"
        )
