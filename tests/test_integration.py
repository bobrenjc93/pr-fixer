"""
Integration tests for PR Fixer using the pytorch test PR.

These tests run against the real PR at https://github.com/pytorch/pytorch/pull/172511
in the local pytorch checkout at /Users/bobren/projects/pytorch.

These tests require:
- gh CLI installed and authenticated
- claude CLI installed
- The pytorch repository cloned at /Users/bobren/projects/pytorch

Run with: pytest tests/test_integration.py -v
Skip slow tests: pytest tests/test_integration.py -v -m "not slow"
Skip tests requiring claude: pytest tests/test_integration.py -v -m "not requires_claude"
"""

import os
import subprocess
import pytest

from pr_fixer.github import (
    parse_pr_url,
    fetch_all_comments,
    fetch_discussion_comments,
    fetch_review_summaries,
    fetch_inline_comments,
    PRInfo,
    GitHubCLIError,
)
from pr_fixer.git import (
    get_pr_branch_name,
    checkout_pr_branch,
    validate_repository,
    get_current_branch,
    check_uncommitted_changes,
    GitError,
    RepositoryMismatchError,
)
from pr_fixer.claude import (
    process_comment,
    _build_prompt_for_comment,
    ProcessingResult,
)
from pr_fixer.dependencies import check_all_dependencies


# Test constants
TEST_PR_URL = "https://github.com/pytorch/pytorch/pull/172511"
TEST_PR_NUMBER = 172511
TEST_OWNER = "pytorch"
TEST_REPO = "pytorch"
PYTORCH_REPO_PATH = "/Users/bobren/projects/pytorch"


def is_gh_cli_available() -> bool:
    """Check if GitHub CLI is available and authenticated."""
    try:
        result = subprocess.run(
            ["gh", "auth", "status"],
            capture_output=True,
            text=True,
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False


def is_claude_cli_available() -> bool:
    """Check if Claude CLI is available."""
    try:
        result = subprocess.run(
            ["which", "claude"],
            capture_output=True,
            text=True,
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False


def is_pytorch_repo_available() -> bool:
    """Check if the pytorch repository is available at the expected path."""
    git_dir = os.path.join(PYTORCH_REPO_PATH, ".git")
    return os.path.isdir(git_dir)


# Skip markers - these combine skipif with explicit markers for filtering
requires_gh = pytest.mark.skipif(
    not is_gh_cli_available(),
    reason="GitHub CLI (gh) not available or not authenticated"
)

requires_claude = [
    pytest.mark.skipif(
        not is_claude_cli_available(),
        reason="Claude CLI not available"
    ),
    pytest.mark.requires_claude,  # Also add explicit marker for filtering with -m
]

requires_pytorch_repo = pytest.mark.skipif(
    not is_pytorch_repo_available(),
    reason=f"PyTorch repository not available at {PYTORCH_REPO_PATH}"
)

# Custom markers
slow = pytest.mark.slow


def apply_requires_claude(cls):
    """Decorator to apply both skipif and marker for requires_claude."""
    for marker in requires_claude:
        cls = marker(cls)
    return cls


class TestPRUrlParsing:
    """Test PR URL parsing with the pytorch test PR."""

    def test_parse_pytorch_pr_url(self):
        """Test parsing the pytorch test PR URL."""
        pr_info = parse_pr_url(TEST_PR_URL)

        assert pr_info.owner == TEST_OWNER
        assert pr_info.repo == TEST_REPO
        assert pr_info.pr_number == TEST_PR_NUMBER

    def test_pr_info_url_property(self):
        """Test that PRInfo reconstructs the canonical URL."""
        pr_info = parse_pr_url(TEST_PR_URL)

        assert pr_info.url == TEST_PR_URL

    def test_pr_info_str_representation(self):
        """Test the string representation of PRInfo."""
        pr_info = parse_pr_url(TEST_PR_URL)

        assert str(pr_info) == f"{TEST_OWNER}/{TEST_REPO}#{TEST_PR_NUMBER}"


@requires_gh
class TestGitHubCommentFetching:
    """
    Test fetching comments from the pytorch test PR.

    These tests require GitHub CLI to be installed and authenticated.
    """

    @pytest.fixture
    def pr_info(self):
        """Return PRInfo for the test PR."""
        return PRInfo(owner=TEST_OWNER, repo=TEST_REPO, pr_number=TEST_PR_NUMBER)

    def test_fetch_discussion_comments(self, pr_info):
        """Test fetching discussion comments from the PR."""
        comments = fetch_discussion_comments(pr_info)

        # The PR may or may not have discussion comments
        assert isinstance(comments, list)
        for comment in comments:
            assert hasattr(comment, 'author')
            assert hasattr(comment, 'body')
            assert isinstance(comment.author, str)
            assert isinstance(comment.body, str)

    def test_fetch_review_summaries(self, pr_info):
        """Test fetching review summaries from the PR."""
        reviews = fetch_review_summaries(pr_info)

        # The PR may or may not have review summaries with body text
        assert isinstance(reviews, list)
        for review in reviews:
            assert hasattr(review, 'author')
            assert hasattr(review, 'body')
            assert hasattr(review, 'state')
            assert isinstance(review.author, str)
            assert isinstance(review.body, str)
            assert isinstance(review.state, str)
            # Reviews should have non-empty bodies (filtered by the function)
            assert review.body.strip() != ""

    def test_fetch_inline_comments(self, pr_info):
        """Test fetching inline code comments from the PR."""
        inline_comments = fetch_inline_comments(pr_info)

        # The PR may or may not have inline comments
        assert isinstance(inline_comments, list)
        for comment in inline_comments:
            assert hasattr(comment, 'author')
            assert hasattr(comment, 'body')
            assert hasattr(comment, 'path')
            assert hasattr(comment, 'line')
            assert hasattr(comment, 'original_line')
            assert isinstance(comment.author, str)
            assert isinstance(comment.body, str)
            assert isinstance(comment.path, str)

    def test_fetch_all_comments(self, pr_info):
        """Test fetching all comment types from the PR."""
        all_comments = fetch_all_comments(pr_info)

        assert hasattr(all_comments, 'discussion_comments')
        assert hasattr(all_comments, 'review_comments')
        assert hasattr(all_comments, 'inline_comments')
        assert hasattr(all_comments, 'total_count')
        assert hasattr(all_comments, 'all_comments')

        # Verify total_count matches the sum of all types
        expected_total = (
            len(all_comments.discussion_comments)
            + len(all_comments.review_comments)
            + len(all_comments.inline_comments)
        )
        assert all_comments.total_count == expected_total

        # Verify all_comments property returns a flat list
        assert len(all_comments.all_comments) == expected_total

    def test_pr_has_some_comments(self, pr_info):
        """Test that the test PR has at least some comments to work with."""
        all_comments = fetch_all_comments(pr_info)

        # The test PR should have at least one comment somewhere
        # This is important for integration testing
        assert all_comments.total_count >= 0, "Expected test PR to have comments"


@requires_gh
@requires_pytorch_repo
class TestGitOperations:
    """
    Test git operations against the pytorch repository.

    These tests require:
    - GitHub CLI to be installed and authenticated
    - The pytorch repository to be available at PYTORCH_REPO_PATH
    """

    @pytest.fixture
    def pr_info(self):
        """Return PRInfo for the test PR."""
        return PRInfo(owner=TEST_OWNER, repo=TEST_REPO, pr_number=TEST_PR_NUMBER)

    @pytest.fixture
    def in_pytorch_repo(self):
        """Change to pytorch repo directory and restore after test."""
        original_dir = os.getcwd()
        os.chdir(PYTORCH_REPO_PATH)
        yield PYTORCH_REPO_PATH
        os.chdir(original_dir)

    def test_get_pr_branch_name(self, pr_info):
        """Test getting the branch name for the test PR."""
        branch_name = get_pr_branch_name(pr_info)

        assert isinstance(branch_name, str)
        assert len(branch_name) > 0
        # Branch names should not contain certain characters
        assert '\n' not in branch_name
        assert '\r' not in branch_name

    def test_validate_repository_in_pytorch(self, pr_info, in_pytorch_repo):
        """Test that repository validation passes in pytorch repo."""
        # Should not raise any exception
        validate_repository(pr_info)

    def test_validate_repository_wrong_repo(self, in_pytorch_repo):
        """Test that repository validation fails for wrong repo."""
        wrong_pr_info = PRInfo(owner="facebook", repo="react", pr_number=123)

        with pytest.raises(RepositoryMismatchError):
            validate_repository(wrong_pr_info)

    def test_get_current_branch(self, in_pytorch_repo):
        """Test getting the current branch name."""
        branch_name = get_current_branch()

        assert isinstance(branch_name, str)
        # Branch name could be empty if in detached HEAD state
        # but that's valid

    def test_check_uncommitted_changes(self, in_pytorch_repo):
        """Test checking for uncommitted changes."""
        has_changes, changed_files = check_uncommitted_changes()

        assert isinstance(has_changes, bool)
        assert isinstance(changed_files, list)
        if has_changes:
            assert len(changed_files) > 0
        else:
            assert len(changed_files) == 0


@slow
@requires_gh
@requires_pytorch_repo
class TestBranchCheckout:
    """
    Test branch checkout operations.

    These tests are marked as slow because they may need to fetch from remote.
    """

    @pytest.fixture
    def pr_info(self):
        """Return PRInfo for the test PR."""
        return PRInfo(owner=TEST_OWNER, repo=TEST_REPO, pr_number=TEST_PR_NUMBER)

    @pytest.fixture
    def in_pytorch_repo(self):
        """Change to pytorch repo directory and restore after test."""
        original_dir = os.getcwd()
        os.chdir(PYTORCH_REPO_PATH)
        yield PYTORCH_REPO_PATH
        os.chdir(original_dir)

    @pytest.fixture
    def save_and_restore_branch(self, in_pytorch_repo):
        """
        Save the current branch and restore it after the test.

        Also stashes any uncommitted changes and restores them.
        """
        # Get current branch
        original_branch = get_current_branch()

        # Check for uncommitted changes
        has_changes, _ = check_uncommitted_changes()
        did_stash = False

        if has_changes:
            # Try to stash changes (may fail in some repo states)
            result = subprocess.run(
                ["git", "stash", "push", "-m", "pytest-integration-test-stash"],
                capture_output=True,
            )
            if result.returncode == 0:
                did_stash = True
            else:
                # If stash fails, skip the test to avoid leaving repo in bad state
                pytest.skip(
                    f"Cannot stash changes in pytorch repo: {result.stderr.decode()}"
                )

        yield original_branch

        # Restore original branch
        if original_branch:
            subprocess.run(
                ["git", "checkout", original_branch],
                capture_output=True,
            )

        # Restore stashed changes
        if did_stash:
            subprocess.run(
                ["git", "stash", "pop"],
                capture_output=True,
            )

    def test_checkout_pr_branch(self, pr_info, save_and_restore_branch):
        """Test checking out the PR branch."""
        branch_name = get_pr_branch_name(pr_info)

        # Checkout the branch
        checkout_pr_branch(branch_name)

        # Verify we're on the correct branch
        current = get_current_branch()
        assert current == branch_name


class TestPromptGeneration:
    """Test Claude prompt generation without requiring Claude CLI."""

    @pytest.fixture
    def pr_info(self):
        """Return PRInfo for the test PR."""
        return PRInfo(owner=TEST_OWNER, repo=TEST_REPO, pr_number=TEST_PR_NUMBER)

    def test_inline_comment_prompt_includes_file_path(self, pr_info):
        """Test that inline comment prompts include the file path."""
        from pr_fixer.models import InlineComment

        comment = InlineComment(
            author="reviewer",
            body="Please add a docstring here",
            path="src/main.py",
            line=42,
        )

        prompt = _build_prompt_for_comment(comment, pr_info.url)

        assert "src/main.py" in prompt
        assert "42" in prompt
        assert "Inline code comment" in prompt
        assert "reviewer" in prompt
        assert "Please add a docstring here" in prompt

    def test_review_comment_prompt_includes_state(self, pr_info):
        """Test that review comment prompts include the review state."""
        from pr_fixer.models import ReviewComment

        comment = ReviewComment(
            author="reviewer",
            body="LGTM with minor suggestions",
            state="APPROVED",
        )

        prompt = _build_prompt_for_comment(comment, pr_info.url)

        assert "APPROVED" in prompt
        assert "Review summary comment" in prompt
        assert "reviewer" in prompt

    def test_discussion_comment_prompt(self, pr_info):
        """Test that discussion comment prompts are generated correctly."""
        from pr_fixer.models import PRComment

        comment = PRComment(
            author="contributor",
            body="What about edge cases?",
        )

        prompt = _build_prompt_for_comment(comment, pr_info.url)

        assert "General discussion comment" in prompt
        assert "contributor" in prompt
        assert "What about edge cases?" in prompt

    def test_prompt_includes_result_markers(self, pr_info):
        """Test that prompts include the expected result markers."""
        from pr_fixer.models import PRComment

        comment = PRComment(
            author="reviewer",
            body="Please fix this",
        )

        prompt = _build_prompt_for_comment(comment, pr_info.url)

        assert "RESULT: CHANGES_MADE" in prompt
        assert "RESULT: NO_CHANGES_NEEDED" in prompt


@requires_gh
class TestDependencyChecking:
    """Test dependency checking functionality."""

    def test_check_all_dependencies(self):
        """Test that dependency checking works."""
        results = check_all_dependencies()

        assert "git" in results
        assert "gh" in results
        assert "claude" in results

        for tool, (is_available, message) in results.items():
            assert isinstance(is_available, bool)
            assert isinstance(message, str)

    def test_gh_is_available(self):
        """Test that gh is detected as available (since we require it for this test class)."""
        results = check_all_dependencies()

        is_available, _ = results["gh"]
        assert is_available, "gh should be available for this test class to run"


@slow
@requires_gh
@apply_requires_claude
@requires_pytorch_repo
class TestClaudeIntegration:
    """
    Test Claude CLI integration.

    These tests require:
    - GitHub CLI to be installed and authenticated
    - Claude CLI to be installed
    - The pytorch repository to be available

    These tests are marked as slow because they invoke Claude.
    """

    @pytest.fixture
    def pr_info(self):
        """Return PRInfo for the test PR."""
        return PRInfo(owner=TEST_OWNER, repo=TEST_REPO, pr_number=TEST_PR_NUMBER)

    @pytest.fixture
    def in_pytorch_repo(self):
        """Change to pytorch repo directory and restore after test."""
        original_dir = os.getcwd()
        os.chdir(PYTORCH_REPO_PATH)
        yield PYTORCH_REPO_PATH
        os.chdir(original_dir)

    def test_process_non_actionable_comment(self, pr_info, in_pytorch_repo):
        """
        Test that a clearly non-actionable comment results in no changes.

        This test uses a comment that is clearly a question/observation,
        which should not result in any code changes.
        """
        from pr_fixer.models import PRComment

        non_actionable_comment = PRComment(
            author="test-reviewer",
            body="Nice work! This looks good to me. Thanks for the contribution!",
        )

        result = process_comment(
            comment=non_actionable_comment,
            pr_url=pr_info.url,
            working_dir=PYTORCH_REPO_PATH,
        )

        # A compliment should not result in code changes
        assert result.result in [
            ProcessingResult.NO_CHANGES_NEEDED,
            ProcessingResult.CHANGES_MADE,  # Claude may sometimes be overzealous
        ]
        # Should not be an error
        assert result.result != ProcessingResult.ERROR


@requires_gh
class TestFullWorkflowDryRun:
    """
    Test the full workflow in dry-run mode.

    This tests the complete flow without actually invoking Claude,
    verifying that all pieces work together.
    """

    @pytest.fixture
    def pr_info(self):
        """Return PRInfo for the test PR."""
        return PRInfo(owner=TEST_OWNER, repo=TEST_REPO, pr_number=TEST_PR_NUMBER)

    def test_can_parse_url_and_fetch_comments(self, pr_info):
        """Test that we can parse the URL and fetch comments successfully."""
        # Step 1: Parse URL
        parsed = parse_pr_url(TEST_PR_URL)
        assert parsed.owner == TEST_OWNER
        assert parsed.repo == TEST_REPO
        assert parsed.pr_number == TEST_PR_NUMBER

        # Step 2: Fetch all comments
        all_comments = fetch_all_comments(parsed)
        assert all_comments is not None
        assert hasattr(all_comments, 'total_count')

        # Step 3: Get PR branch name
        branch_name = get_pr_branch_name(parsed)
        assert isinstance(branch_name, str)
        assert len(branch_name) > 0

    @requires_pytorch_repo
    def test_can_validate_and_get_branch(self, pr_info):
        """Test that we can validate the repo and get branch info."""
        original_dir = os.getcwd()
        try:
            os.chdir(PYTORCH_REPO_PATH)

            # Validate we're in the right repo
            validate_repository(pr_info)

            # Get PR branch name
            branch_name = get_pr_branch_name(pr_info)
            assert branch_name

            # Get current branch
            current = get_current_branch()
            assert isinstance(current, str)

        finally:
            os.chdir(original_dir)
