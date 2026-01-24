"""Tests for git module."""

import json
import subprocess
from unittest.mock import patch, MagicMock, call

import pytest
from pr_fixer.git import (
    get_pr_branch_name,
    checkout_pr_branch,
    checkout_ghstack_pr,
    is_ghstack_pr,
    check_ghstack_available,
    validate_repository,
    get_current_branch,
    check_uncommitted_changes,
    require_clean_working_directory,
    GitError,
    GitHubCLIError,
    GhstackError,
    RepositoryMismatchError,
    UncommittedChangesError,
)
from pr_fixer.github import PRInfo


class TestIsGhstackPR:
    """Tests for is_ghstack_pr function."""

    def test_ghstack_head_branch(self):
        """Test detection of ghstack head branch."""
        assert is_ghstack_pr("gh/username/123/head") is True

    def test_ghstack_base_branch(self):
        """Test detection of ghstack base branch."""
        assert is_ghstack_pr("gh/username/456/base") is True

    def test_ghstack_orig_branch(self):
        """Test detection of ghstack orig branch."""
        assert is_ghstack_pr("gh/user/789/orig") is True

    def test_regular_feature_branch(self):
        """Test that regular feature branches are not detected as ghstack."""
        assert is_ghstack_pr("feature/my-feature") is False

    def test_main_branch(self):
        """Test that main branch is not detected as ghstack."""
        assert is_ghstack_pr("main") is False

    def test_branch_with_slashes(self):
        """Test that branches with slashes but wrong pattern are not ghstack."""
        assert is_ghstack_pr("user/feature/add-thing") is False

    def test_gh_prefix_wrong_format(self):
        """Test that gh prefix with wrong format is not ghstack."""
        assert is_ghstack_pr("gh/username") is False
        assert is_ghstack_pr("gh/username/123") is False
        assert is_ghstack_pr("gh/username/not-a-number/head") is False

    def test_ghstack_with_complex_username(self):
        """Test ghstack detection with complex usernames."""
        assert is_ghstack_pr("gh/user-name_123/456/head") is True


class TestCheckGhstackAvailable:
    """Tests for check_ghstack_available function."""

    @patch("pr_fixer.git.shutil.which")
    def test_ghstack_available(self, mock_which):
        """Test that returns True when ghstack is available."""
        mock_which.return_value = "/usr/local/bin/ghstack"

        assert check_ghstack_available() is True
        mock_which.assert_called_once_with("ghstack")

    @patch("pr_fixer.git.shutil.which")
    def test_ghstack_not_available(self, mock_which):
        """Test that returns False when ghstack is not available."""
        mock_which.return_value = None

        assert check_ghstack_available() is False


class TestCheckoutGhstackPR:
    """Tests for checkout_ghstack_pr function."""

    @patch("pr_fixer.git.check_ghstack_available")
    @patch("pr_fixer.git.subprocess.run")
    def test_successful_checkout(self, mock_run, mock_available):
        """Test successful ghstack checkout."""
        mock_available.return_value = True
        mock_run.return_value = MagicMock(returncode=0)

        checkout_ghstack_pr("https://github.com/owner/repo/pull/123")

        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd == ["ghstack", "checkout", "https://github.com/owner/repo/pull/123"]

    @patch("pr_fixer.git.check_ghstack_available")
    @patch("pr_fixer.git.subprocess.run")
    def test_checkout_with_cwd(self, mock_run, mock_available):
        """Test ghstack checkout with working directory."""
        mock_available.return_value = True
        mock_run.return_value = MagicMock(returncode=0)

        checkout_ghstack_pr("https://github.com/owner/repo/pull/123", cwd="/path/to/repo")

        call_kwargs = mock_run.call_args[1]
        assert call_kwargs.get("cwd") == "/path/to/repo"

    @patch("pr_fixer.git.check_ghstack_available")
    def test_ghstack_not_installed(self, mock_available):
        """Test error when ghstack is not installed."""
        mock_available.return_value = False

        with pytest.raises(GhstackError) as exc_info:
            checkout_ghstack_pr("https://github.com/owner/repo/pull/123")
        assert "ghstack is not installed" in str(exc_info.value)
        assert "pip install ghstack" in str(exc_info.value)

    @patch("pr_fixer.git.check_ghstack_available")
    @patch("pr_fixer.git.subprocess.run")
    def test_checkout_command_fails(self, mock_run, mock_available):
        """Test error when ghstack checkout command fails."""
        mock_available.return_value = True
        mock_run.side_effect = subprocess.CalledProcessError(
            returncode=1,
            cmd=["ghstack", "checkout"],
            stderr="PR not found"
        )

        with pytest.raises(GhstackError) as exc_info:
            checkout_ghstack_pr("https://github.com/owner/repo/pull/999")
        assert "Failed to checkout PR with ghstack" in str(exc_info.value)

    @patch("pr_fixer.git.check_ghstack_available")
    @patch("pr_fixer.git.subprocess.run")
    def test_ghstack_file_not_found(self, mock_run, mock_available):
        """Test error when ghstack binary disappears mid-execution."""
        mock_available.return_value = True
        mock_run.side_effect = FileNotFoundError()

        with pytest.raises(GhstackError) as exc_info:
            checkout_ghstack_pr("https://github.com/owner/repo/pull/123")
        assert "ghstack not found" in str(exc_info.value)


class TestGetPRBranchName:
    """Tests for get_pr_branch_name function."""

    @pytest.fixture
    def pr_info(self):
        """Sample PRInfo for testing."""
        return PRInfo(owner="pytorch", repo="pytorch", pr_number=172511)

    @patch("pr_fixer.git.subprocess.run")
    def test_successful_fetch(self, mock_run, pr_info):
        """Test fetching PR branch name successfully."""
        mock_run.return_value = MagicMock(
            stdout=json.dumps({"headRefName": "feature/my-branch"}),
            returncode=0
        )

        result = get_pr_branch_name(pr_info)

        assert result == "feature/my-branch"

    @patch("pr_fixer.git.subprocess.run")
    def test_branch_name_with_slashes(self, mock_run, pr_info):
        """Test branch name with multiple slashes."""
        mock_run.return_value = MagicMock(
            stdout=json.dumps({"headRefName": "user/feature/add-new-thing"}),
            returncode=0
        )

        result = get_pr_branch_name(pr_info)

        assert result == "user/feature/add-new-thing"

    @patch("pr_fixer.git.subprocess.run")
    def test_correct_command_called(self, mock_run, pr_info):
        """Test that the correct gh command is called."""
        mock_run.return_value = MagicMock(
            stdout='{"headRefName": "main"}',
            returncode=0
        )

        get_pr_branch_name(pr_info)

        mock_run.assert_called_once()
        call_args = mock_run.call_args
        cmd = call_args[0][0]
        assert cmd == [
            "gh", "pr", "view", "172511",
            "--repo", "pytorch/pytorch",
            "--json", "headRefName"
        ]

    @patch("pr_fixer.git.subprocess.run")
    def test_cli_error_raises_exception(self, mock_run, pr_info):
        """Test that CLI errors raise GitHubCLIError."""
        mock_run.side_effect = subprocess.CalledProcessError(
            returncode=1,
            cmd=["gh", "pr", "view"],
            stderr="PR not found"
        )

        with pytest.raises(GitHubCLIError) as exc_info:
            get_pr_branch_name(pr_info)
        assert "Failed to get PR branch name" in str(exc_info.value)

    @patch("pr_fixer.git.subprocess.run")
    def test_gh_not_found_raises_exception(self, mock_run, pr_info):
        """Test that missing gh CLI raises GitHubCLIError."""
        mock_run.side_effect = FileNotFoundError()

        with pytest.raises(GitHubCLIError) as exc_info:
            get_pr_branch_name(pr_info)
        assert "GitHub CLI (gh) not found" in str(exc_info.value)

    @patch("pr_fixer.git.subprocess.run")
    def test_invalid_json_raises_exception(self, mock_run, pr_info):
        """Test that invalid JSON output raises GitHubCLIError."""
        mock_run.return_value = MagicMock(
            stdout="not valid json",
            returncode=0
        )

        with pytest.raises(GitHubCLIError) as exc_info:
            get_pr_branch_name(pr_info)
        assert "Failed to parse gh CLI output as JSON" in str(exc_info.value)

    @patch("pr_fixer.git.subprocess.run")
    def test_missing_head_ref_name_raises_exception(self, mock_run, pr_info):
        """Test that missing headRefName raises GitHubCLIError."""
        mock_run.return_value = MagicMock(
            stdout=json.dumps({}),
            returncode=0
        )

        with pytest.raises(GitHubCLIError) as exc_info:
            get_pr_branch_name(pr_info)
        assert "No branch name found" in str(exc_info.value)

    @patch("pr_fixer.git.subprocess.run")
    def test_empty_head_ref_name_raises_exception(self, mock_run, pr_info):
        """Test that empty headRefName raises GitHubCLIError."""
        mock_run.return_value = MagicMock(
            stdout=json.dumps({"headRefName": ""}),
            returncode=0
        )

        with pytest.raises(GitHubCLIError) as exc_info:
            get_pr_branch_name(pr_info)
        assert "No branch name found" in str(exc_info.value)

    @patch("pr_fixer.git.subprocess.run")
    def test_uses_different_pr_info(self, mock_run):
        """Test that different PRInfo values are used correctly."""
        pr_info = PRInfo(owner="my-org", repo="my-repo", pr_number=456)
        mock_run.return_value = MagicMock(
            stdout='{"headRefName": "fix/bug"}',
            returncode=0
        )

        result = get_pr_branch_name(pr_info)

        assert result == "fix/bug"
        call_args = mock_run.call_args
        cmd = call_args[0][0]
        assert "456" in cmd
        assert "my-org/my-repo" in cmd


class TestCheckoutPRBranch:
    """Tests for checkout_pr_branch function."""

    @patch("pr_fixer.git.subprocess.run")
    def test_local_branch_exists_checkout_succeeds(self, mock_run):
        """Test checkout succeeds when local branch exists."""
        mock_run.return_value = MagicMock(returncode=0)

        checkout_pr_branch("feature/existing-branch")

        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd == ["git", "checkout", "feature/existing-branch"]

    @patch("pr_fixer.git.subprocess.run")
    def test_local_branch_missing_checkout_from_remote_tracking(self, mock_run):
        """Test checkout creates branch from remote tracking when local doesn't exist."""
        # First call: checkout fails (local branch doesn't exist)
        # Second call: checkout with tracking succeeds
        mock_run.side_effect = [
            MagicMock(returncode=1, stderr="error: pathspec did not match"),
            MagicMock(returncode=0)
        ]

        checkout_pr_branch("feature/new-branch")

        assert mock_run.call_count == 2
        first_cmd = mock_run.call_args_list[0][0][0]
        second_cmd = mock_run.call_args_list[1][0][0]
        assert first_cmd == ["git", "checkout", "feature/new-branch"]
        assert second_cmd == ["git", "checkout", "-b", "feature/new-branch", "origin/feature/new-branch"]

    @patch("pr_fixer.git.subprocess.run")
    def test_needs_fetch_then_checkout(self, mock_run):
        """Test checkout fetches from remote when tracking branch doesn't exist."""
        # First call: checkout fails (local branch doesn't exist)
        # Second call: checkout with tracking fails (remote tracking doesn't exist)
        # Third call: fetch with branch creation succeeds
        # Fourth call: checkout succeeds
        mock_run.side_effect = [
            MagicMock(returncode=1, stderr="error: pathspec did not match"),
            MagicMock(returncode=1, stderr="fatal: Cannot update paths"),
            MagicMock(returncode=0),  # fetch succeeds
            MagicMock(returncode=0),  # checkout succeeds
        ]

        checkout_pr_branch("feature/remote-branch")

        assert mock_run.call_count == 4
        fetch_cmd = mock_run.call_args_list[2][0][0]
        assert fetch_cmd == ["git", "fetch", "origin", "feature/remote-branch:feature/remote-branch"]

    @patch("pr_fixer.git.subprocess.run")
    def test_simple_fetch_fallback(self, mock_run):
        """Test fallback to simple fetch when fetch with branch creation fails."""
        # First call: checkout fails
        # Second call: checkout with tracking fails
        # Third call: fetch with branch creation fails
        # Fourth call: simple fetch succeeds
        # Fifth call: checkout with tracking succeeds
        def side_effect(*args, **kwargs):
            cmd = args[0]
            if cmd == ["git", "checkout", "feature/branch"]:
                return MagicMock(returncode=1, stderr="error: pathspec")
            elif cmd == ["git", "checkout", "-b", "feature/branch", "origin/feature/branch"]:
                # Return failure first time, success second time
                if hasattr(side_effect, 'track_calls'):
                    return MagicMock(returncode=0)
                return MagicMock(returncode=1, stderr="fatal: Cannot update")
            elif cmd == ["git", "fetch", "origin", "feature/branch:feature/branch"]:
                raise subprocess.CalledProcessError(1, cmd, stderr="error: couldn't find remote ref")
            elif cmd == ["git", "fetch", "origin", "feature/branch"]:
                return MagicMock(returncode=0)
            return MagicMock(returncode=0)

        mock_run.side_effect = [
            MagicMock(returncode=1, stderr="error: pathspec"),
            MagicMock(returncode=1, stderr="fatal: Cannot update"),
            subprocess.CalledProcessError(1, [], stderr="couldn't find"),  # fetch with branch fails
            MagicMock(returncode=0),  # simple fetch succeeds
            MagicMock(returncode=0),  # checkout with tracking succeeds
        ]

        checkout_pr_branch("feature/branch")

        assert mock_run.call_count == 5

    @patch("pr_fixer.git.subprocess.run")
    def test_fetch_failure_raises_git_error(self, mock_run):
        """Test that fetch failure raises GitError."""
        mock_run.side_effect = [
            MagicMock(returncode=1, stderr="error: pathspec"),
            MagicMock(returncode=1, stderr="fatal: Cannot update"),
            subprocess.CalledProcessError(1, [], stderr="couldn't find"),  # fetch with branch fails
            subprocess.CalledProcessError(1, [], stderr="fatal: couldn't find remote ref"),  # simple fetch fails
        ]

        with pytest.raises(GitError) as exc_info:
            checkout_pr_branch("feature/nonexistent")
        assert "Failed to fetch branch" in str(exc_info.value)

    @patch("pr_fixer.git.subprocess.run")
    def test_git_not_found_raises_error(self, mock_run):
        """Test that missing git raises GitError."""
        mock_run.side_effect = [
            MagicMock(returncode=1),
            MagicMock(returncode=1),
            subprocess.CalledProcessError(1, []),
            FileNotFoundError(),
        ]

        with pytest.raises(GitError) as exc_info:
            checkout_pr_branch("feature/branch")
        assert "git not found" in str(exc_info.value)


class TestValidateRepository:
    """Tests for validate_repository function."""

    @pytest.fixture
    def pr_info(self):
        """Sample PRInfo for testing."""
        return PRInfo(owner="pytorch", repo="pytorch", pr_number=172511)

    @patch("pr_fixer.git.subprocess.run")
    def test_https_remote_matches(self, mock_run, pr_info):
        """Test validation passes with matching HTTPS remote."""
        mock_run.return_value = MagicMock(
            stdout="origin\thttps://github.com/pytorch/pytorch.git (fetch)\n"
                   "origin\thttps://github.com/pytorch/pytorch.git (push)\n",
            returncode=0
        )

        # Should not raise
        validate_repository(pr_info)

    @patch("pr_fixer.git.subprocess.run")
    def test_https_remote_without_git_suffix(self, mock_run, pr_info):
        """Test validation passes with HTTPS remote without .git suffix."""
        mock_run.return_value = MagicMock(
            stdout="origin\thttps://github.com/pytorch/pytorch (fetch)\n",
            returncode=0
        )

        validate_repository(pr_info)

    @patch("pr_fixer.git.subprocess.run")
    def test_ssh_remote_matches(self, mock_run, pr_info):
        """Test validation passes with matching SSH remote."""
        mock_run.return_value = MagicMock(
            stdout="origin\tgit@github.com:pytorch/pytorch.git (fetch)\n"
                   "origin\tgit@github.com:pytorch/pytorch.git (push)\n",
            returncode=0
        )

        validate_repository(pr_info)

    @patch("pr_fixer.git.subprocess.run")
    def test_ssh_protocol_remote_matches(self, mock_run, pr_info):
        """Test validation passes with SSH protocol URL."""
        mock_run.return_value = MagicMock(
            stdout="origin\tssh://git@github.com/pytorch/pytorch.git (fetch)\n",
            returncode=0
        )

        validate_repository(pr_info)

    @patch("pr_fixer.git.subprocess.run")
    def test_case_insensitive_matching(self, mock_run, pr_info):
        """Test that owner/repo matching is case-insensitive."""
        mock_run.return_value = MagicMock(
            stdout="origin\thttps://github.com/PyTorch/PYTORCH.git (fetch)\n",
            returncode=0
        )

        validate_repository(pr_info)

    @patch("pr_fixer.git.subprocess.run")
    def test_multiple_remotes_one_matches(self, mock_run, pr_info):
        """Test validation passes if any remote matches."""
        mock_run.return_value = MagicMock(
            stdout="upstream\thttps://github.com/pytorch/pytorch.git (fetch)\n"
                   "upstream\thttps://github.com/pytorch/pytorch.git (push)\n"
                   "origin\thttps://github.com/fork/pytorch.git (fetch)\n"
                   "origin\thttps://github.com/fork/pytorch.git (push)\n",
            returncode=0
        )

        validate_repository(pr_info)

    @patch("pr_fixer.git.subprocess.run")
    def test_wrong_repo_raises_mismatch_error(self, mock_run, pr_info):
        """Test that wrong repository raises RepositoryMismatchError."""
        mock_run.return_value = MagicMock(
            stdout="origin\thttps://github.com/different/repo.git (fetch)\n",
            returncode=0
        )

        with pytest.raises(RepositoryMismatchError) as exc_info:
            validate_repository(pr_info)
        assert "Repository mismatch" in str(exc_info.value)
        assert "pytorch/pytorch" in str(exc_info.value)
        assert "different/repo" in str(exc_info.value)

    @patch("pr_fixer.git.subprocess.run")
    def test_no_remotes_raises_git_error(self, mock_run, pr_info):
        """Test that no remotes raises GitError."""
        mock_run.return_value = MagicMock(
            stdout="",
            returncode=0
        )

        with pytest.raises(GitError) as exc_info:
            validate_repository(pr_info)
        assert "No git remotes found" in str(exc_info.value)

    @patch("pr_fixer.git.subprocess.run")
    def test_non_github_remotes_raises_git_error(self, mock_run, pr_info):
        """Test that non-GitHub remotes raise GitError."""
        mock_run.return_value = MagicMock(
            stdout="origin\thttps://gitlab.com/owner/repo.git (fetch)\n",
            returncode=0
        )

        with pytest.raises(GitError) as exc_info:
            validate_repository(pr_info)
        assert "Could not parse any GitHub remote URLs" in str(exc_info.value)

    @patch("pr_fixer.git.subprocess.run")
    def test_git_command_failure_raises_git_error(self, mock_run, pr_info):
        """Test that git command failure raises GitError."""
        mock_run.side_effect = subprocess.CalledProcessError(
            returncode=1,
            cmd=["git", "remote", "-v"],
            stderr="fatal: not a git repository"
        )

        with pytest.raises(GitError) as exc_info:
            validate_repository(pr_info)
        assert "Failed to get git remotes" in str(exc_info.value)

    @patch("pr_fixer.git.subprocess.run")
    def test_git_not_found_raises_git_error(self, mock_run, pr_info):
        """Test that missing git raises GitError."""
        mock_run.side_effect = FileNotFoundError()

        with pytest.raises(GitError) as exc_info:
            validate_repository(pr_info)
        assert "git not found" in str(exc_info.value)

    @patch("pr_fixer.git.subprocess.run")
    def test_correct_command_called(self, mock_run, pr_info):
        """Test that the correct git command is called."""
        mock_run.return_value = MagicMock(
            stdout="origin\thttps://github.com/pytorch/pytorch.git (fetch)\n",
            returncode=0
        )

        validate_repository(pr_info)

        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd == ["git", "remote", "-v"]


class TestGetCurrentBranch:
    """Tests for get_current_branch function."""

    @patch("pr_fixer.git.subprocess.run")
    def test_returns_current_branch(self, mock_run):
        """Test that current branch name is returned."""
        mock_run.return_value = MagicMock(
            stdout="main\n",
            returncode=0
        )

        result = get_current_branch()

        assert result == "main"

    @patch("pr_fixer.git.subprocess.run")
    def test_handles_feature_branch(self, mock_run):
        """Test handling of feature branch names."""
        mock_run.return_value = MagicMock(
            stdout="feature/my-feature\n",
            returncode=0
        )

        result = get_current_branch()

        assert result == "feature/my-feature"

    @patch("pr_fixer.git.subprocess.run")
    def test_strips_whitespace(self, mock_run):
        """Test that whitespace is stripped from output."""
        mock_run.return_value = MagicMock(
            stdout="  develop  \n",
            returncode=0
        )

        result = get_current_branch()

        assert result == "develop"

    @patch("pr_fixer.git.subprocess.run")
    def test_correct_command_called(self, mock_run):
        """Test that the correct git command is called."""
        mock_run.return_value = MagicMock(
            stdout="main\n",
            returncode=0
        )

        get_current_branch()

        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd == ["git", "branch", "--show-current"]

    @patch("pr_fixer.git.subprocess.run")
    def test_git_error_raises_exception(self, mock_run):
        """Test that git errors raise GitError."""
        mock_run.side_effect = subprocess.CalledProcessError(
            returncode=1,
            cmd=["git", "branch", "--show-current"],
            stderr="fatal: not a git repository"
        )

        with pytest.raises(GitError) as exc_info:
            get_current_branch()
        assert "Failed to get current branch" in str(exc_info.value)

    @patch("pr_fixer.git.subprocess.run")
    def test_git_not_found_raises_exception(self, mock_run):
        """Test that missing git raises GitError."""
        mock_run.side_effect = FileNotFoundError()

        with pytest.raises(GitError) as exc_info:
            get_current_branch()
        assert "git not found" in str(exc_info.value)

    @patch("pr_fixer.git.subprocess.run")
    def test_detached_head_returns_empty(self, mock_run):
        """Test that detached HEAD returns empty string."""
        mock_run.return_value = MagicMock(
            stdout="\n",
            returncode=0
        )

        result = get_current_branch()

        assert result == ""


class TestCheckUncommittedChanges:
    """Tests for check_uncommitted_changes function."""

    @patch("pr_fixer.git.subprocess.run")
    def test_no_changes_returns_false(self, mock_run):
        """Test that clean working directory returns False."""
        mock_run.return_value = MagicMock(
            stdout="",
            returncode=0
        )

        has_changes, files = check_uncommitted_changes()

        assert has_changes is False
        assert files == []

    @patch("pr_fixer.git.subprocess.run")
    def test_modified_file_returns_true(self, mock_run):
        """Test that modified file returns True with file list."""
        mock_run.return_value = MagicMock(
            stdout=" M file.py\n",
            returncode=0
        )

        has_changes, files = check_uncommitted_changes()

        assert has_changes is True
        assert files == ["file.py"]

    @patch("pr_fixer.git.subprocess.run")
    def test_multiple_changes(self, mock_run):
        """Test handling of multiple changed files."""
        mock_run.return_value = MagicMock(
            stdout=" M src/file1.py\n M src/file2.py\n?? new_file.txt\n",
            returncode=0
        )

        has_changes, files = check_uncommitted_changes()

        assert has_changes is True
        assert len(files) == 3
        assert "src/file1.py" in files
        assert "src/file2.py" in files
        assert "new_file.txt" in files

    @patch("pr_fixer.git.subprocess.run")
    def test_staged_changes(self, mock_run):
        """Test that staged changes are detected."""
        mock_run.return_value = MagicMock(
            stdout="M  staged_file.py\n",
            returncode=0
        )

        has_changes, files = check_uncommitted_changes()

        assert has_changes is True
        assert "staged_file.py" in files

    @patch("pr_fixer.git.subprocess.run")
    def test_untracked_files(self, mock_run):
        """Test that untracked files are detected."""
        mock_run.return_value = MagicMock(
            stdout="?? untracked.txt\n",
            returncode=0
        )

        has_changes, files = check_uncommitted_changes()

        assert has_changes is True
        assert "untracked.txt" in files

    @patch("pr_fixer.git.subprocess.run")
    def test_correct_command_called(self, mock_run):
        """Test that the correct git command is called."""
        mock_run.return_value = MagicMock(
            stdout="",
            returncode=0
        )

        check_uncommitted_changes()

        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd == ["git", "status", "--porcelain"]

    @patch("pr_fixer.git.subprocess.run")
    def test_git_error_raises_exception(self, mock_run):
        """Test that git errors raise GitError."""
        mock_run.side_effect = subprocess.CalledProcessError(
            returncode=1,
            cmd=["git", "status", "--porcelain"],
            stderr="fatal: not a git repository"
        )

        with pytest.raises(GitError) as exc_info:
            check_uncommitted_changes()
        assert "Failed to check git status" in str(exc_info.value)

    @patch("pr_fixer.git.subprocess.run")
    def test_git_not_found_raises_exception(self, mock_run):
        """Test that missing git raises GitError."""
        mock_run.side_effect = FileNotFoundError()

        with pytest.raises(GitError) as exc_info:
            check_uncommitted_changes()
        assert "git not found" in str(exc_info.value)


class TestRequireCleanWorkingDirectory:
    """Tests for require_clean_working_directory function."""

    @patch("pr_fixer.git.check_uncommitted_changes")
    def test_clean_directory_passes(self, mock_check):
        """Test that clean working directory doesn't raise."""
        mock_check.return_value = (False, [])

        # Should not raise
        require_clean_working_directory()

    @patch("pr_fixer.git.check_uncommitted_changes")
    def test_uncommitted_changes_raises_error(self, mock_check):
        """Test that uncommitted changes raise UncommittedChangesError."""
        mock_check.return_value = (True, ["file1.py", "file2.py"])

        with pytest.raises(UncommittedChangesError) as exc_info:
            require_clean_working_directory()
        assert "uncommitted changes" in str(exc_info.value)
        assert "file1.py" in str(exc_info.value)
        assert "file2.py" in str(exc_info.value)

    @patch("pr_fixer.git.check_uncommitted_changes")
    def test_error_message_includes_stash_instructions(self, mock_check):
        """Test that error message includes git stash instructions."""
        mock_check.return_value = (True, ["file.py"])

        with pytest.raises(UncommittedChangesError) as exc_info:
            require_clean_working_directory()
        assert "git stash" in str(exc_info.value)
        assert "git stash pop" in str(exc_info.value)

    @patch("pr_fixer.git.check_uncommitted_changes")
    def test_many_files_shows_preview(self, mock_check):
        """Test that many files show preview with count."""
        files = [f"file{i}.py" for i in range(10)]
        mock_check.return_value = (True, files)

        with pytest.raises(UncommittedChangesError) as exc_info:
            require_clean_working_directory()
        assert "and 5 more" in str(exc_info.value)

    @patch("pr_fixer.git.check_uncommitted_changes")
    def test_exactly_five_files_no_more_message(self, mock_check):
        """Test that exactly 5 files doesn't show 'more' message."""
        files = [f"file{i}.py" for i in range(5)]
        mock_check.return_value = (True, files)

        with pytest.raises(UncommittedChangesError) as exc_info:
            require_clean_working_directory()
        assert "more" not in str(exc_info.value)
        for f in files:
            assert f in str(exc_info.value)

    @patch("pr_fixer.git.check_uncommitted_changes")
    def test_git_error_propagates(self, mock_check):
        """Test that GitError from check_uncommitted_changes propagates."""
        mock_check.side_effect = GitError("Failed to check git status")

        with pytest.raises(GitError) as exc_info:
            require_clean_working_directory()
        assert "Failed to check git status" in str(exc_info.value)
