"""Tests for GitHub module."""

import json
import subprocess
from unittest.mock import patch, MagicMock

import pytest
from pr_fixer.github import (
    parse_pr_url,
    PRInfo,
    InvalidPRURLError,
    GitHubCLIError,
    fetch_discussion_comments,
    fetch_review_summaries,
    fetch_inline_comments,
    fetch_all_comments,
)
from pr_fixer.models import PRComment, ReviewComment, InlineComment, AllComments, CommentType


class TestParsePRUrl:
    """Tests for parse_pr_url function."""

    def test_basic_url(self):
        """Test parsing a basic PR URL."""
        result = parse_pr_url("https://github.com/pytorch/pytorch/pull/172511")
        assert result.owner == "pytorch"
        assert result.repo == "pytorch"
        assert result.pr_number == 172511

    def test_url_with_trailing_slash(self):
        """Test parsing a PR URL with trailing slash."""
        result = parse_pr_url("https://github.com/owner/repo/pull/123/")
        assert result.owner == "owner"
        assert result.repo == "repo"
        assert result.pr_number == 123

    def test_url_with_files_tab(self):
        """Test parsing a PR URL pointing to files tab."""
        result = parse_pr_url("https://github.com/owner/repo/pull/123/files")
        assert result.owner == "owner"
        assert result.repo == "repo"
        assert result.pr_number == 123

    def test_url_with_commits_tab(self):
        """Test parsing a PR URL pointing to commits tab."""
        result = parse_pr_url("https://github.com/owner/repo/pull/456/commits")
        assert result.owner == "owner"
        assert result.repo == "repo"
        assert result.pr_number == 456

    def test_url_with_query_params(self):
        """Test parsing a PR URL with query parameters."""
        result = parse_pr_url("https://github.com/owner/repo/pull/789?diff=split&w=1")
        assert result.owner == "owner"
        assert result.repo == "repo"
        assert result.pr_number == 789

    def test_url_with_anchor(self):
        """Test parsing a PR URL with anchor."""
        result = parse_pr_url("https://github.com/owner/repo/pull/101#discussion_r123")
        assert result.owner == "owner"
        assert result.repo == "repo"
        assert result.pr_number == 101

    def test_url_with_query_and_anchor(self):
        """Test parsing a PR URL with both query params and anchor."""
        result = parse_pr_url("https://github.com/owner/repo/pull/202?foo=bar#anchor")
        assert result.owner == "owner"
        assert result.repo == "repo"
        assert result.pr_number == 202

    def test_http_url(self):
        """Test parsing an http:// URL (not https)."""
        result = parse_pr_url("http://github.com/owner/repo/pull/303")
        assert result.owner == "owner"
        assert result.repo == "repo"
        assert result.pr_number == 303

    def test_url_without_scheme(self):
        """Test parsing a URL without http/https scheme."""
        result = parse_pr_url("github.com/owner/repo/pull/404")
        assert result.owner == "owner"
        assert result.repo == "repo"
        assert result.pr_number == 404

    def test_www_github_url(self):
        """Test parsing a www.github.com URL."""
        result = parse_pr_url("https://www.github.com/owner/repo/pull/505")
        assert result.owner == "owner"
        assert result.repo == "repo"
        assert result.pr_number == 505

    def test_url_with_whitespace(self):
        """Test parsing a URL with leading/trailing whitespace."""
        result = parse_pr_url("  https://github.com/owner/repo/pull/606  ")
        assert result.owner == "owner"
        assert result.repo == "repo"
        assert result.pr_number == 606

    def test_hyphenated_owner_and_repo(self):
        """Test parsing URL with hyphens in owner and repo names."""
        result = parse_pr_url("https://github.com/my-org/my-repo-name/pull/707")
        assert result.owner == "my-org"
        assert result.repo == "my-repo-name"
        assert result.pr_number == 707

    def test_underscored_owner_and_repo(self):
        """Test parsing URL with underscores in owner and repo names."""
        result = parse_pr_url("https://github.com/my_org/my_repo_name/pull/808")
        assert result.owner == "my_org"
        assert result.repo == "my_repo_name"
        assert result.pr_number == 808

    def test_numeric_repo_name(self):
        """Test parsing URL with numeric characters in repo name."""
        result = parse_pr_url("https://github.com/owner/repo123/pull/909")
        assert result.owner == "owner"
        assert result.repo == "repo123"
        assert result.pr_number == 909


class TestParsePRUrlInvalid:
    """Tests for invalid URLs that should raise InvalidPRURLError."""

    def test_empty_string(self):
        """Test that empty string raises error."""
        with pytest.raises(InvalidPRURLError):
            parse_pr_url("")

    def test_none_value(self):
        """Test that None raises error."""
        with pytest.raises(InvalidPRURLError):
            parse_pr_url(None)

    def test_non_github_url(self):
        """Test that non-GitHub URL raises error."""
        with pytest.raises(InvalidPRURLError) as exc_info:
            parse_pr_url("https://gitlab.com/owner/repo/pull/123")
        assert "github.com" in str(exc_info.value)

    def test_github_non_pr_url(self):
        """Test that GitHub URL that's not a PR raises error."""
        with pytest.raises(InvalidPRURLError):
            parse_pr_url("https://github.com/owner/repo/issues/123")

    def test_github_repo_url(self):
        """Test that repo URL without PR number raises error."""
        with pytest.raises(InvalidPRURLError):
            parse_pr_url("https://github.com/owner/repo")

    def test_github_pulls_list_url(self):
        """Test that pulls list URL (no specific PR) raises error."""
        with pytest.raises(InvalidPRURLError):
            parse_pr_url("https://github.com/owner/repo/pulls")

    def test_missing_pr_number(self):
        """Test that URL without PR number raises error."""
        with pytest.raises(InvalidPRURLError):
            parse_pr_url("https://github.com/owner/repo/pull/")

    def test_invalid_pr_number(self):
        """Test that non-numeric PR number raises error."""
        with pytest.raises(InvalidPRURLError):
            parse_pr_url("https://github.com/owner/repo/pull/abc")

    def test_random_string(self):
        """Test that random string raises error."""
        with pytest.raises(InvalidPRURLError):
            parse_pr_url("not a url at all")

    def test_only_scheme(self):
        """Test that URL with only scheme raises error."""
        with pytest.raises(InvalidPRURLError):
            parse_pr_url("https://")


class TestPRInfo:
    """Tests for PRInfo dataclass."""

    def test_str_representation(self):
        """Test string representation of PRInfo."""
        info = PRInfo(owner="pytorch", repo="pytorch", pr_number=172511)
        assert str(info) == "pytorch/pytorch#172511"

    def test_url_property(self):
        """Test URL reconstruction from PRInfo."""
        info = PRInfo(owner="pytorch", repo="pytorch", pr_number=172511)
        assert info.url == "https://github.com/pytorch/pytorch/pull/172511"

    def test_equality(self):
        """Test equality comparison of PRInfo."""
        info1 = PRInfo(owner="owner", repo="repo", pr_number=123)
        info2 = PRInfo(owner="owner", repo="repo", pr_number=123)
        assert info1 == info2

    def test_inequality(self):
        """Test inequality when values differ."""
        info1 = PRInfo(owner="owner", repo="repo", pr_number=123)
        info2 = PRInfo(owner="owner", repo="repo", pr_number=456)
        assert info1 != info2


class TestFetchDiscussionComments:
    """Tests for fetch_discussion_comments function."""

    @pytest.fixture
    def pr_info(self):
        """Sample PRInfo for testing."""
        return PRInfo(owner="pytorch", repo="pytorch", pr_number=172511)

    @patch("pr_fixer.github.subprocess.run")
    def test_successful_fetch_with_comments(self, mock_run, pr_info):
        """Test fetching discussion comments successfully."""
        mock_output = {
            "comments": [
                {"author": {"login": "user1"}, "body": "This looks good!"},
                {"author": {"login": "user2"}, "body": "Please fix the typo."},
            ]
        }
        mock_run.return_value = MagicMock(
            stdout=json.dumps(mock_output),
            returncode=0
        )

        comments = fetch_discussion_comments(pr_info)

        assert len(comments) == 2
        assert comments[0].author == "user1"
        assert comments[0].body == "This looks good!"
        assert comments[0].comment_type == CommentType.DISCUSSION
        assert comments[1].author == "user2"
        assert comments[1].body == "Please fix the typo."

    @patch("pr_fixer.github.subprocess.run")
    def test_successful_fetch_empty_comments(self, mock_run, pr_info):
        """Test fetching when there are no discussion comments."""
        mock_output = {"comments": []}
        mock_run.return_value = MagicMock(
            stdout=json.dumps(mock_output),
            returncode=0
        )

        comments = fetch_discussion_comments(pr_info)

        assert len(comments) == 0
        assert comments == []

    @patch("pr_fixer.github.subprocess.run")
    def test_missing_author_field(self, mock_run, pr_info):
        """Test handling when author field is missing."""
        mock_output = {
            "comments": [
                {"body": "Comment without author"},
            ]
        }
        mock_run.return_value = MagicMock(
            stdout=json.dumps(mock_output),
            returncode=0
        )

        comments = fetch_discussion_comments(pr_info)

        assert len(comments) == 1
        assert comments[0].author == "unknown"
        assert comments[0].body == "Comment without author"

    @patch("pr_fixer.github.subprocess.run")
    def test_missing_body_field(self, mock_run, pr_info):
        """Test handling when body field is missing."""
        mock_output = {
            "comments": [
                {"author": {"login": "user1"}},
            ]
        }
        mock_run.return_value = MagicMock(
            stdout=json.dumps(mock_output),
            returncode=0
        )

        comments = fetch_discussion_comments(pr_info)

        assert len(comments) == 1
        assert comments[0].body == ""

    @patch("pr_fixer.github.subprocess.run")
    def test_cli_error_raises_exception(self, mock_run, pr_info):
        """Test that CLI errors raise GitHubCLIError."""
        mock_run.side_effect = subprocess.CalledProcessError(
            returncode=1,
            cmd=["gh", "pr", "view"],
            stderr="PR not found"
        )

        with pytest.raises(GitHubCLIError) as exc_info:
            fetch_discussion_comments(pr_info)
        assert "Failed to fetch PR comments" in str(exc_info.value)

    @patch("pr_fixer.github.subprocess.run")
    def test_gh_not_found_raises_exception(self, mock_run, pr_info):
        """Test that missing gh CLI raises GitHubCLIError."""
        mock_run.side_effect = FileNotFoundError()

        with pytest.raises(GitHubCLIError) as exc_info:
            fetch_discussion_comments(pr_info)
        assert "GitHub CLI (gh) not found" in str(exc_info.value)

    @patch("pr_fixer.github.subprocess.run")
    def test_invalid_json_raises_exception(self, mock_run, pr_info):
        """Test that invalid JSON output raises GitHubCLIError."""
        mock_run.return_value = MagicMock(
            stdout="not valid json",
            returncode=0
        )

        with pytest.raises(GitHubCLIError) as exc_info:
            fetch_discussion_comments(pr_info)
        assert "Failed to parse gh CLI output" in str(exc_info.value)

    @patch("pr_fixer.github.subprocess.run")
    def test_correct_command_called(self, mock_run, pr_info):
        """Test that the correct gh command is called."""
        mock_run.return_value = MagicMock(
            stdout='{"comments": []}',
            returncode=0
        )

        fetch_discussion_comments(pr_info)

        mock_run.assert_called_once()
        call_args = mock_run.call_args
        cmd = call_args[0][0]
        assert cmd == [
            "gh", "pr", "view", "172511",
            "--repo", "pytorch/pytorch",
            "--json", "comments"
        ]


class TestFetchReviewSummaries:
    """Tests for fetch_review_summaries function."""

    @pytest.fixture
    def pr_info(self):
        """Sample PRInfo for testing."""
        return PRInfo(owner="pytorch", repo="pytorch", pr_number=172511)

    @patch("pr_fixer.github.subprocess.run")
    def test_successful_fetch_with_reviews(self, mock_run, pr_info):
        """Test fetching review summaries successfully."""
        mock_output = [
            {
                "user": {"login": "reviewer1"},
                "body": "LGTM, great changes!",
                "state": "APPROVED"
            },
            {
                "user": {"login": "reviewer2"},
                "body": "Please address my concerns.",
                "state": "CHANGES_REQUESTED"
            },
        ]
        mock_run.return_value = MagicMock(
            stdout=json.dumps(mock_output),
            returncode=0
        )

        reviews = fetch_review_summaries(pr_info)

        assert len(reviews) == 2
        assert reviews[0].author == "reviewer1"
        assert reviews[0].body == "LGTM, great changes!"
        assert reviews[0].state == "APPROVED"
        assert reviews[1].author == "reviewer2"
        assert reviews[1].body == "Please address my concerns."
        assert reviews[1].state == "CHANGES_REQUESTED"

    @patch("pr_fixer.github.subprocess.run")
    def test_filters_empty_bodies(self, mock_run, pr_info):
        """Test that reviews with empty bodies are filtered out."""
        mock_output = [
            {"user": {"login": "reviewer1"}, "body": "Valid comment", "state": "APPROVED"},
            {"user": {"login": "reviewer2"}, "body": "", "state": "APPROVED"},
            {"user": {"login": "reviewer3"}, "body": "   ", "state": "APPROVED"},
            {"user": {"login": "reviewer4"}, "body": "Another valid", "state": "COMMENTED"},
        ]
        mock_run.return_value = MagicMock(
            stdout=json.dumps(mock_output),
            returncode=0
        )

        reviews = fetch_review_summaries(pr_info)

        assert len(reviews) == 2
        assert reviews[0].author == "reviewer1"
        assert reviews[1].author == "reviewer4"

    @patch("pr_fixer.github.subprocess.run")
    def test_successful_fetch_empty_reviews(self, mock_run, pr_info):
        """Test fetching when there are no reviews."""
        mock_run.return_value = MagicMock(
            stdout="[]",
            returncode=0
        )

        reviews = fetch_review_summaries(pr_info)

        assert len(reviews) == 0

    @patch("pr_fixer.github.subprocess.run")
    def test_missing_user_field(self, mock_run, pr_info):
        """Test handling when user field is missing."""
        mock_output = [
            {"body": "Review without user", "state": "APPROVED"}
        ]
        mock_run.return_value = MagicMock(
            stdout=json.dumps(mock_output),
            returncode=0
        )

        reviews = fetch_review_summaries(pr_info)

        assert len(reviews) == 1
        assert reviews[0].author == "unknown"

    @patch("pr_fixer.github.subprocess.run")
    def test_missing_state_field(self, mock_run, pr_info):
        """Test handling when state field is missing."""
        mock_output = [
            {"user": {"login": "reviewer1"}, "body": "Some review"}
        ]
        mock_run.return_value = MagicMock(
            stdout=json.dumps(mock_output),
            returncode=0
        )

        reviews = fetch_review_summaries(pr_info)

        assert len(reviews) == 1
        assert reviews[0].state == "UNKNOWN"

    @patch("pr_fixer.github.subprocess.run")
    def test_cli_error_raises_exception(self, mock_run, pr_info):
        """Test that CLI errors raise GitHubCLIError."""
        mock_run.side_effect = subprocess.CalledProcessError(
            returncode=1,
            cmd=["gh", "api"],
            stderr="Not Found"
        )

        with pytest.raises(GitHubCLIError) as exc_info:
            fetch_review_summaries(pr_info)
        assert "Failed to fetch PR reviews" in str(exc_info.value)

    @patch("pr_fixer.github.subprocess.run")
    def test_gh_not_found_raises_exception(self, mock_run, pr_info):
        """Test that missing gh CLI raises GitHubCLIError."""
        mock_run.side_effect = FileNotFoundError()

        with pytest.raises(GitHubCLIError) as exc_info:
            fetch_review_summaries(pr_info)
        assert "GitHub CLI (gh) not found" in str(exc_info.value)

    @patch("pr_fixer.github.subprocess.run")
    def test_invalid_json_raises_exception(self, mock_run, pr_info):
        """Test that invalid JSON output raises GitHubCLIError."""
        mock_run.return_value = MagicMock(
            stdout="not valid json",
            returncode=0
        )

        with pytest.raises(GitHubCLIError) as exc_info:
            fetch_review_summaries(pr_info)
        assert "Failed to parse gh CLI output" in str(exc_info.value)

    @patch("pr_fixer.github.subprocess.run")
    def test_correct_command_called(self, mock_run, pr_info):
        """Test that the correct gh api command is called."""
        mock_run.return_value = MagicMock(
            stdout="[]",
            returncode=0
        )

        fetch_review_summaries(pr_info)

        mock_run.assert_called_once()
        call_args = mock_run.call_args
        cmd = call_args[0][0]
        assert cmd == [
            "gh", "api",
            "repos/pytorch/pytorch/pulls/172511/reviews"
        ]


class TestFetchInlineComments:
    """Tests for fetch_inline_comments function."""

    @pytest.fixture
    def pr_info(self):
        """Sample PRInfo for testing."""
        return PRInfo(owner="pytorch", repo="pytorch", pr_number=172511)

    @patch("pr_fixer.github.subprocess.run")
    def test_successful_fetch_with_inline_comments(self, mock_run, pr_info):
        """Test fetching inline comments successfully."""
        mock_output = [
            {
                "user": {"login": "reviewer1"},
                "body": "Consider using a constant here.",
                "path": "src/file.py",
                "line": 42,
                "original_line": None
            },
            {
                "user": {"login": "reviewer2"},
                "body": "This could be simplified.",
                "path": "src/other.py",
                "line": None,
                "original_line": 100
            },
        ]
        mock_run.return_value = MagicMock(
            stdout=json.dumps(mock_output),
            returncode=0
        )

        comments = fetch_inline_comments(pr_info)

        assert len(comments) == 2
        assert comments[0].author == "reviewer1"
        assert comments[0].body == "Consider using a constant here."
        assert comments[0].path == "src/file.py"
        assert comments[0].line == 42
        assert comments[0].original_line is None
        assert comments[1].author == "reviewer2"
        assert comments[1].path == "src/other.py"
        assert comments[1].line is None
        assert comments[1].original_line == 100

    @patch("pr_fixer.github.subprocess.run")
    def test_successful_fetch_empty_comments(self, mock_run, pr_info):
        """Test fetching when there are no inline comments."""
        mock_run.return_value = MagicMock(
            stdout="[]",
            returncode=0
        )

        comments = fetch_inline_comments(pr_info)

        assert len(comments) == 0

    @patch("pr_fixer.github.subprocess.run")
    def test_missing_user_field(self, mock_run, pr_info):
        """Test handling when user field is missing."""
        mock_output = [
            {"body": "Comment", "path": "file.py", "line": 10}
        ]
        mock_run.return_value = MagicMock(
            stdout=json.dumps(mock_output),
            returncode=0
        )

        comments = fetch_inline_comments(pr_info)

        assert len(comments) == 1
        assert comments[0].author == "unknown"

    @patch("pr_fixer.github.subprocess.run")
    def test_missing_path_field(self, mock_run, pr_info):
        """Test handling when path field is missing."""
        mock_output = [
            {"user": {"login": "user1"}, "body": "Comment", "line": 10}
        ]
        mock_run.return_value = MagicMock(
            stdout=json.dumps(mock_output),
            returncode=0
        )

        comments = fetch_inline_comments(pr_info)

        assert len(comments) == 1
        assert comments[0].path == ""

    @patch("pr_fixer.github.subprocess.run")
    def test_both_line_and_original_line(self, mock_run, pr_info):
        """Test when both line and original_line are present."""
        mock_output = [
            {
                "user": {"login": "user1"},
                "body": "Comment",
                "path": "file.py",
                "line": 50,
                "original_line": 45
            }
        ]
        mock_run.return_value = MagicMock(
            stdout=json.dumps(mock_output),
            returncode=0
        )

        comments = fetch_inline_comments(pr_info)

        assert len(comments) == 1
        assert comments[0].line == 50
        assert comments[0].original_line == 45
        assert comments[0].effective_line == 50

    @patch("pr_fixer.github.subprocess.run")
    def test_cli_error_raises_exception(self, mock_run, pr_info):
        """Test that CLI errors raise GitHubCLIError."""
        mock_run.side_effect = subprocess.CalledProcessError(
            returncode=1,
            cmd=["gh", "api"],
            stderr="Not Found"
        )

        with pytest.raises(GitHubCLIError) as exc_info:
            fetch_inline_comments(pr_info)
        assert "Failed to fetch inline comments" in str(exc_info.value)

    @patch("pr_fixer.github.subprocess.run")
    def test_gh_not_found_raises_exception(self, mock_run, pr_info):
        """Test that missing gh CLI raises GitHubCLIError."""
        mock_run.side_effect = FileNotFoundError()

        with pytest.raises(GitHubCLIError) as exc_info:
            fetch_inline_comments(pr_info)
        assert "GitHub CLI (gh) not found" in str(exc_info.value)

    @patch("pr_fixer.github.subprocess.run")
    def test_invalid_json_raises_exception(self, mock_run, pr_info):
        """Test that invalid JSON output raises GitHubCLIError."""
        mock_run.return_value = MagicMock(
            stdout="not valid json",
            returncode=0
        )

        with pytest.raises(GitHubCLIError) as exc_info:
            fetch_inline_comments(pr_info)
        assert "Failed to parse gh CLI output" in str(exc_info.value)

    @patch("pr_fixer.github.subprocess.run")
    def test_correct_command_called(self, mock_run, pr_info):
        """Test that the correct gh api command is called."""
        mock_run.return_value = MagicMock(
            stdout="[]",
            returncode=0
        )

        fetch_inline_comments(pr_info)

        mock_run.assert_called_once()
        call_args = mock_run.call_args
        cmd = call_args[0][0]
        assert cmd == [
            "gh", "api",
            "repos/pytorch/pytorch/pulls/172511/comments"
        ]


class TestFetchAllComments:
    """Tests for fetch_all_comments function."""

    @pytest.fixture
    def pr_info(self):
        """Sample PRInfo for testing."""
        return PRInfo(owner="owner", repo="repo", pr_number=123)

    @patch("pr_fixer.github.fetch_inline_comments")
    @patch("pr_fixer.github.fetch_review_summaries")
    @patch("pr_fixer.github.fetch_discussion_comments")
    def test_combines_all_comment_types(
        self, mock_discussion, mock_reviews, mock_inline, pr_info
    ):
        """Test that all comment types are combined correctly."""
        mock_discussion.return_value = [
            PRComment(author="user1", body="Discussion comment")
        ]
        mock_reviews.return_value = [
            ReviewComment(author="reviewer1", body="Review comment", state="APPROVED")
        ]
        mock_inline.return_value = [
            InlineComment(
                author="reviewer2",
                body="Inline comment",
                path="file.py",
                line=10
            )
        ]

        result = fetch_all_comments(pr_info)

        assert isinstance(result, AllComments)
        assert len(result.discussion_comments) == 1
        assert len(result.review_comments) == 1
        assert len(result.inline_comments) == 1
        assert result.total_count == 3
        assert len(result.all_comments) == 3

    @patch("pr_fixer.github.fetch_inline_comments")
    @patch("pr_fixer.github.fetch_review_summaries")
    @patch("pr_fixer.github.fetch_discussion_comments")
    def test_handles_empty_comments(
        self, mock_discussion, mock_reviews, mock_inline, pr_info
    ):
        """Test that empty comments are handled correctly."""
        mock_discussion.return_value = []
        mock_reviews.return_value = []
        mock_inline.return_value = []

        result = fetch_all_comments(pr_info)

        assert result.total_count == 0
        assert len(result.all_comments) == 0

    @patch("pr_fixer.github.fetch_inline_comments")
    @patch("pr_fixer.github.fetch_review_summaries")
    @patch("pr_fixer.github.fetch_discussion_comments")
    def test_passes_pr_info_to_all_functions(
        self, mock_discussion, mock_reviews, mock_inline, pr_info
    ):
        """Test that PRInfo is passed to all fetch functions."""
        mock_discussion.return_value = []
        mock_reviews.return_value = []
        mock_inline.return_value = []

        fetch_all_comments(pr_info)

        mock_discussion.assert_called_once_with(pr_info)
        mock_reviews.assert_called_once_with(pr_info)
        mock_inline.assert_called_once_with(pr_info)

    @patch("pr_fixer.github.fetch_inline_comments")
    @patch("pr_fixer.github.fetch_review_summaries")
    @patch("pr_fixer.github.fetch_discussion_comments")
    def test_discussion_error_propagates(
        self, mock_discussion, mock_reviews, mock_inline, pr_info
    ):
        """Test that errors from discussion comments propagate."""
        mock_discussion.side_effect = GitHubCLIError("Discussion fetch failed")

        with pytest.raises(GitHubCLIError) as exc_info:
            fetch_all_comments(pr_info)
        assert "Discussion fetch failed" in str(exc_info.value)

    @patch("pr_fixer.github.fetch_inline_comments")
    @patch("pr_fixer.github.fetch_review_summaries")
    @patch("pr_fixer.github.fetch_discussion_comments")
    def test_review_error_propagates(
        self, mock_discussion, mock_reviews, mock_inline, pr_info
    ):
        """Test that errors from review summaries propagate."""
        mock_discussion.return_value = []
        mock_reviews.side_effect = GitHubCLIError("Review fetch failed")

        with pytest.raises(GitHubCLIError) as exc_info:
            fetch_all_comments(pr_info)
        assert "Review fetch failed" in str(exc_info.value)

    @patch("pr_fixer.github.fetch_inline_comments")
    @patch("pr_fixer.github.fetch_review_summaries")
    @patch("pr_fixer.github.fetch_discussion_comments")
    def test_inline_error_propagates(
        self, mock_discussion, mock_reviews, mock_inline, pr_info
    ):
        """Test that errors from inline comments propagate."""
        mock_discussion.return_value = []
        mock_reviews.return_value = []
        mock_inline.side_effect = GitHubCLIError("Inline fetch failed")

        with pytest.raises(GitHubCLIError) as exc_info:
            fetch_all_comments(pr_info)
        assert "Inline fetch failed" in str(exc_info.value)

    @patch("pr_fixer.github.fetch_inline_comments")
    @patch("pr_fixer.github.fetch_review_summaries")
    @patch("pr_fixer.github.fetch_discussion_comments")
    def test_multiple_comments_per_type(
        self, mock_discussion, mock_reviews, mock_inline, pr_info
    ):
        """Test handling multiple comments of each type."""
        mock_discussion.return_value = [
            PRComment(author="user1", body="Comment 1"),
            PRComment(author="user2", body="Comment 2"),
        ]
        mock_reviews.return_value = [
            ReviewComment(author="reviewer1", body="Review 1", state="APPROVED"),
            ReviewComment(author="reviewer2", body="Review 2", state="CHANGES_REQUESTED"),
            ReviewComment(author="reviewer3", body="Review 3", state="COMMENTED"),
        ]
        mock_inline.return_value = [
            InlineComment(author="user3", body="Inline 1", path="a.py", line=1),
        ]

        result = fetch_all_comments(pr_info)

        assert len(result.discussion_comments) == 2
        assert len(result.review_comments) == 3
        assert len(result.inline_comments) == 1
        assert result.total_count == 6
