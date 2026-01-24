"""CLI entry point and argument parsing for PR Fixer."""

import argparse
import os
import sys
from typing import Optional

from .github import parse_pr_url, fetch_all_comments, PRInfo, InvalidPRURLError, GitHubCLIError
from .git import (
    validate_repository,
    get_pr_branch_name,
    checkout_pr_branch,
    get_current_branch,
    check_uncommitted_changes,
    require_clean_working_directory,
    GitError,
    GitHubCLIError as GitGitHubCLIError,
    RepositoryMismatchError,
    UncommittedChangesError,
)
from .claude import (
    process_all_comments_with_progress,
    ClaudeError,
)
from .dependencies import (
    check_all_dependencies,
    require_all_dependencies,
    require_gh_authentication,
    format_dependency_status,
    DependencyError,
    AuthenticationError,
)


def create_parser() -> argparse.ArgumentParser:
    """Create and configure the argument parser."""
    parser = argparse.ArgumentParser(
        prog="pr-fixer",
        description="A CLI tool that automates addressing PR review comments using Claude AI.",
        epilog="Example: pr-fixer https://github.com/owner/repo/pull/123",
    )

    parser.add_argument(
        "pr_url",
        nargs="?",
        help="The GitHub PR URL to process (e.g., https://github.com/owner/repo/pull/123)",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would happen without making changes",
    )

    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose output",
    )

    parser.add_argument(
        "--check-deps",
        action="store_true",
        help="Check for required dependencies and exit",
    )

    parser.add_argument(
        "--skip-checkout",
        action="store_true",
        help="Skip branch checkout (use current branch instead)",
    )

    parser.add_argument(
        "-d", "--directory",
        metavar="PATH",
        help="Path to the local repository (defaults to current directory)",
    )

    parser.add_argument(
        "--version",
        action="version",
        version="%(prog)s 0.1.0",
    )

    return parser


def main() -> int:
    """Main entry point for the CLI."""
    parser = create_parser()
    args = parser.parse_args()

    # Handle --check-deps flag
    if args.check_deps:
        results = check_all_dependencies()
        print(format_dependency_status(results))
        all_ok = all(is_available for is_available, _ in results.values())
        if all_ok:
            print("\nAll dependencies are available.")
            return 0
        else:
            print("\nSome dependencies are missing. See above for details.")
            return 1

    if args.pr_url is None:
        parser.print_help()
        return 0

    # Check for required dependencies at startup
    try:
        require_all_dependencies()
    except DependencyError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    # Check GitHub CLI authentication
    try:
        require_gh_authentication()
    except AuthenticationError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except DependencyError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    # Validate and parse the PR URL
    try:
        pr_info = parse_pr_url(args.pr_url)
    except InvalidPRURLError as e:
        print(f"Error: {e}", file=sys.stderr)
        print("\nExpected format: https://github.com/owner/repo/pull/123", file=sys.stderr)
        return 1

    if args.verbose:
        print(f"Parsed PR: {pr_info}")
        print(f"  Owner: {pr_info.owner}")
        print(f"  Repo: {pr_info.repo}")
        print(f"  PR Number: {pr_info.pr_number}")
        print()

    # Resolve the working directory
    if args.directory:
        working_dir = os.path.abspath(os.path.expanduser(args.directory))
        if not os.path.isdir(working_dir):
            print(f"Error: Directory does not exist: {working_dir}", file=sys.stderr)
            return 1
    else:
        working_dir = os.getcwd()

    # Step 1: Validate we're in the correct repository
    print(f"Processing PR: {pr_info.url}")
    print()

    try:
        validate_repository(pr_info, cwd=working_dir)
        if args.verbose:
            print("Repository validation passed.")
    except RepositoryMismatchError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except GitError as e:
        print(f"Git error: {e}", file=sys.stderr)
        return 1

    # Step 2: Get the PR branch name
    try:
        branch_name = get_pr_branch_name(pr_info)
        if args.verbose:
            print(f"PR branch: {branch_name}")
    except (GitHubCLIError, GitGitHubCLIError) as e:
        print(f"Error fetching PR branch name: {e}", file=sys.stderr)
        return 1

    # Step 3: Checkout the PR branch (unless --skip-checkout is set)
    if args.skip_checkout:
        if args.verbose:
            print(f"Skipping checkout (--skip-checkout flag set)")
        try:
            current_branch = get_current_branch(cwd=working_dir)
            print(f"Using current branch: {current_branch}")
        except GitError:
            print("Using current branch.")
        print()
    else:
        # Check for uncommitted changes before checkout
        try:
            require_clean_working_directory(cwd=working_dir)
        except UncommittedChangesError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
        except GitError as e:
            print(f"Git error: {e}", file=sys.stderr)
            return 1

        current_branch = None
        try:
            current_branch = get_current_branch(cwd=working_dir)
            if args.verbose:
                print(f"Current branch: {current_branch}")
        except GitError as e:
            if args.verbose:
                print(f"Warning: Could not determine current branch: {e}")

        try:
            print(f"Checking out branch: {branch_name}")
            checkout_pr_branch(branch_name, cwd=working_dir)
            print(f"Successfully checked out branch: {branch_name}")
            print()
        except GitError as e:
            print(f"Error checking out branch: {e}", file=sys.stderr)
            return 1

    # Step 4: Fetch all comments from the PR
    print("Fetching PR comments...")
    try:
        all_comments = fetch_all_comments(pr_info)
        if args.verbose:
            print(f"  Discussion comments: {len(all_comments.discussion_comments)}")
            print(f"  Review comments: {len(all_comments.review_comments)}")
            print(f"  Inline comments: {len(all_comments.inline_comments)}")
        print(f"Found {all_comments.total_count} comment(s) total.")
        print()
    except GitHubCLIError as e:
        print(f"Error fetching PR comments: {e}", file=sys.stderr)
        return 1

    # Handle dry-run mode: show what would be processed without invoking Claude
    if args.dry_run:
        print("[Dry run] Would process the following comments:")
        print()
        for i, comment in enumerate(all_comments.all_comments, 1):
            print(f"  {i}. {comment}")
        print()
        print("[Dry run] No changes made.")
        return 0

    # Step 5: Process each comment with Claude
    if all_comments.total_count == 0:
        print("No comments to process. Done!")
        return 0

    try:
        result = process_all_comments_with_progress(
            all_comments=all_comments,
            pr_url=pr_info.url,
            working_dir=working_dir,
            verbose=args.verbose,
        )
    except ClaudeError as e:
        print(f"Error invoking Claude: {e}", file=sys.stderr)
        return 1

    # Final summary
    print()
    if result.success:
        if result.changes_made_count > 0:
            print(f"Done! Created {result.changes_made_count} commit(s).")
            print("Review the changes and push when ready.")
        else:
            print("Done! No changes were needed.")
    else:
        print(f"Completed with {result.error_count} error(s).", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
