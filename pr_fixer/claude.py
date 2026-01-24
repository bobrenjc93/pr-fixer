"""Claude integration for fixing PR comments."""

import subprocess
import sys
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Callable, TextIO

if TYPE_CHECKING:
    from .models import Comment, InlineComment, AllComments


class ClaudeError(Exception):
    """Raised when Claude CLI invocation fails."""
    pass


class ProcessingResult(Enum):
    """Result of processing a comment with Claude."""
    CHANGES_MADE = "changes_made"  # Claude made changes and committed
    NO_CHANGES_NEEDED = "no_changes_needed"  # Comment didn't require changes
    ERROR = "error"  # An error occurred during processing


@dataclass
class CommentProcessingResult:
    """Result of processing a single comment."""
    result: ProcessingResult
    message: str  # Human-readable description of what happened
    stdout: str = ""  # Claude's stdout output
    stderr: str = ""  # Claude's stderr output


def _build_prompt_for_comment(comment: "Comment", pr_url: str) -> str:
    """
    Build a prompt for Claude to process a PR comment.

    The prompt instructs Claude to:
    1. Analyze the comment to determine if code changes are needed
    2. If changes are needed, make them and commit with a descriptive message
    3. If no changes are needed, do nothing

    Args:
        comment: The comment to process
        pr_url: The URL of the PR for context

    Returns:
        A prompt string for Claude
    """
    from .models import InlineComment, ReviewComment, PRComment

    # Build context based on comment type
    if isinstance(comment, InlineComment):
        location_context = f"""COMMENT TYPE: Inline code comment
FILE: {comment.path}
LINE: {comment.effective_line or 'unknown'}

IMPORTANT: Start by reading the file at {comment.path} to understand the context before making any changes."""
    elif isinstance(comment, ReviewComment):
        state_explanation = {
            "APPROVED": "The reviewer approved the PR but left this comment",
            "CHANGES_REQUESTED": "The reviewer requested changes - this comment likely needs action",
            "COMMENTED": "The reviewer left a general comment",
        }.get(comment.state, f"Review state: {comment.state}")
        location_context = f"""COMMENT TYPE: Review summary comment
REVIEW STATE: {comment.state}
CONTEXT: {state_explanation}"""
    else:
        location_context = """COMMENT TYPE: General discussion comment on the PR"""

    prompt = f"""You are an AI assistant helping to address PR review comments.

=== CONTEXT ===
PR URL: {pr_url}
{location_context}
Comment Author: {comment.author}

=== COMMENT TO ADDRESS ===
{comment.body}

=== YOUR TASK ===
Analyze this PR comment and determine if it requires code changes.

ACTIONABLE comments that DO require changes (make changes and commit):
- Requests to fix bugs or errors
- Requests to add/remove/modify code
- Requests to rename variables, functions, or files
- Style or formatting fixes requested
- Requests to add documentation or comments to code
- Suggestions that the author should implement (e.g., "please add...", "can you fix...", "this should be...")

NON-ACTIONABLE comments that do NOT require changes (do nothing):
- Questions asking for clarification ("Why did you do this?", "What does this mean?")
- General observations or acknowledgments ("Looks good", "Nice work", "I see")
- Discussion or debate about approaches (not a direct request to change)
- Comments the PR author already addressed in a reply
- FYI or informational comments
- Compliments or praise

=== INSTRUCTIONS ===
1. If the comment IS ACTIONABLE and requires code changes:
   a. Read any relevant files to understand the current state
   b. Make the necessary code changes
   c. Create a git commit with this message format:

      Address review comment: <brief summary of what you changed>

      Reviewer ({comment.author}) requested: <paraphrase the comment>

      Changes made:
      - <bullet point describing change 1>
      - <bullet point describing change 2 if applicable>

   d. After committing, output: "RESULT: CHANGES_MADE - <brief description>"

2. If the comment is NOT ACTIONABLE:
   - Do NOT make any code changes
   - Do NOT create any commits
   - Output: "RESULT: NO_CHANGES_NEEDED - <reason why no changes are needed>"

=== IMPORTANT RULES ===
- NEVER create empty commits
- NEVER commit if you haven't actually changed any code
- When in doubt about whether a comment is actionable, err on the side of NOT making changes
- If the comment is vague or ambiguous, do NOT make changes
- Make minimal, focused changes that directly address the comment
- Do not refactor or "improve" unrelated code

Begin by analyzing the comment, then take the appropriate action."""

    return prompt


def process_comment(comment: "Comment", pr_url: str, working_dir: str | None = None) -> CommentProcessingResult:
    """
    Process a single PR comment using Claude CLI.

    Invokes Claude with a prompt describing the comment and instructs it to
    make changes and commit if necessary.

    Args:
        comment: The comment to process (PRComment, ReviewComment, or InlineComment)
        pr_url: The URL of the PR for context
        working_dir: Optional working directory to run Claude in (defaults to current directory)

    Returns:
        CommentProcessingResult with the outcome of processing

    Raises:
        ClaudeError: If the Claude CLI is not available or fails unexpectedly
    """
    prompt = _build_prompt_for_comment(comment, pr_url)

    # Build the Claude CLI command
    # Using claude -p for programmatic/non-interactive mode
    cmd = ["claude", "-p", "--dangerously-skip-permissions", prompt]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=working_dir,
            timeout=300  # 5 minute timeout for Claude to work
        )
    except FileNotFoundError:
        raise ClaudeError(
            "Claude CLI not found. Please install Claude Code CLI and ensure 'claude' is in your PATH."
        )
    except subprocess.TimeoutExpired:
        raise ClaudeError(
            "Claude CLI timed out after 5 minutes. The operation may be taking too long."
        )
    except Exception as e:
        raise ClaudeError(f"Failed to run Claude CLI: {e}") from e

    # Analyze the result
    # Claude CLI returns 0 on success
    if result.returncode != 0:
        return CommentProcessingResult(
            result=ProcessingResult.ERROR,
            message=f"Claude CLI returned non-zero exit code: {result.returncode}",
            stdout=result.stdout,
            stderr=result.stderr
        )

    # Check stdout for indication of what happened
    stdout_content = result.stdout
    stdout_lower = stdout_content.lower()

    # First, check for structured output format from our prompt
    # These are the explicit markers we ask Claude to output
    if "result: changes_made" in stdout_lower:
        return CommentProcessingResult(
            result=ProcessingResult.CHANGES_MADE,
            message="Claude made changes and created a commit",
            stdout=stdout_content,
            stderr=result.stderr
        )

    if "result: no_changes_needed" in stdout_lower:
        return CommentProcessingResult(
            result=ProcessingResult.NO_CHANGES_NEEDED,
            message="Claude determined no code changes were needed",
            stdout=stdout_content,
            stderr=result.stderr
        )

    # Fallback: Heuristics to detect if Claude made changes
    # This handles cases where Claude doesn't follow the structured format exactly
    commit_indicators = [
        "created commit",
        "committed",
        "git commit",
        "made commit",
        "changes committed",
        "commit created",
    ]

    no_change_indicators = [
        "no changes needed",
        "no changes required",
        "no code changes",
        "doesn't require changes",
        "does not require changes",
        "not actionable",
        "no action needed",
        "no action required",
        "non-actionable",
    ]

    # Check for no-change indicators first (safer default)
    for indicator in no_change_indicators:
        if indicator in stdout_lower:
            return CommentProcessingResult(
                result=ProcessingResult.NO_CHANGES_NEEDED,
                message="Claude determined no code changes were needed",
                stdout=stdout_content,
                stderr=result.stderr
            )

    # Check for commit indicators
    for indicator in commit_indicators:
        if indicator in stdout_lower:
            return CommentProcessingResult(
                result=ProcessingResult.CHANGES_MADE,
                message="Claude made changes and created a commit",
                stdout=stdout_content,
                stderr=result.stderr
            )

    # Default: assume no changes if we can't determine
    return CommentProcessingResult(
        result=ProcessingResult.NO_CHANGES_NEEDED,
        message="Claude processed the comment (unclear if changes were made)",
        stdout=stdout_content,
        stderr=result.stderr
    )


@dataclass
class AllCommentsProcessingResult:
    """Result of processing all comments in a PR."""
    results: list[tuple["Comment", CommentProcessingResult]]  # List of (comment, result) pairs
    total_comments: int
    changes_made_count: int
    no_changes_count: int
    error_count: int

    @property
    def success(self) -> bool:
        """Return True if all comments were processed without errors."""
        return self.error_count == 0


class ProgressReporter:
    """
    Progress reporter for comment processing.

    Provides formatted output for tracking progress during comment processing,
    including "Processing comment X/Y..." messages and result summaries.
    """

    def __init__(self, output: TextIO | None = None, verbose: bool = False):
        """
        Initialize the progress reporter.

        Args:
            output: The output stream to write to (defaults to sys.stdout)
            verbose: If True, include more detailed information in output
        """
        self.output = output or sys.stdout
        self.verbose = verbose

    def _write(self, message: str, newline: bool = True) -> None:
        """Write a message to the output stream."""
        if newline:
            print(message, file=self.output)
        else:
            print(message, end="", file=self.output, flush=True)

    def on_start(self, total_comments: int) -> None:
        """Called before processing begins."""
        if total_comments == 0:
            self._write("No comments to process.")
        else:
            self._write(f"Found {total_comments} comment(s) to process.\n")

    def on_comment_start(self, index: int, total: int, comment: "Comment") -> None:
        """
        Called before processing each comment.

        This is the callback to pass to process_all_comments as on_progress.

        Args:
            index: Zero-based index of the current comment
            total: Total number of comments to process
            comment: The comment about to be processed
        """
        from .models import InlineComment, ReviewComment

        # Create a brief description of the comment
        if isinstance(comment, InlineComment):
            location = f" on {comment.path}"
            if comment.effective_line:
                location += f":{comment.effective_line}"
        elif isinstance(comment, ReviewComment):
            location = f" ({comment.state})"
        else:
            location = ""

        self._write(f"Processing comment {index + 1}/{total}{location}...")

        if self.verbose:
            # Show truncated comment body in verbose mode
            body_preview = comment.body[:100].replace("\n", " ")
            if len(comment.body) > 100:
                body_preview += "..."
            self._write(f"  Author: {comment.author}")
            self._write(f"  Comment: {body_preview}")

    def on_comment_complete(self, index: int, total: int, comment: "Comment", result: CommentProcessingResult) -> None:
        """
        Called after processing each comment.

        Args:
            index: Zero-based index of the current comment
            total: Total number of comments to process
            comment: The comment that was processed
            result: The result of processing
        """
        if result.result == ProcessingResult.CHANGES_MADE:
            status = "  -> Changes made and committed"
        elif result.result == ProcessingResult.NO_CHANGES_NEEDED:
            status = "  -> No changes needed"
        else:
            status = f"  -> Error: {result.message}"

        self._write(status)
        self._write("")  # Blank line between comments

    def on_complete(self, result: "AllCommentsProcessingResult") -> None:
        """Called after all processing is complete."""
        self._write("=" * 40)
        self._write("Processing complete!")
        self._write(f"  Total comments: {result.total_comments}")
        self._write(f"  Changes made: {result.changes_made_count}")
        self._write(f"  No changes needed: {result.no_changes_count}")
        if result.error_count > 0:
            self._write(f"  Errors: {result.error_count}")


def create_progress_callback(reporter: ProgressReporter) -> Callable[[int, int, "Comment"], None]:
    """
    Create a progress callback function for use with process_all_comments.

    Args:
        reporter: The ProgressReporter to use for output

    Returns:
        A callback function compatible with process_all_comments on_progress parameter
    """
    return reporter.on_comment_start


def process_all_comments(
    all_comments: "AllComments",
    pr_url: str,
    working_dir: str | None = None,
    on_progress: Callable[[int, int, "Comment"], None] | None = None,
    on_comment_complete: Callable[[int, int, "Comment", CommentProcessingResult], None] | None = None,
) -> AllCommentsProcessingResult:
    """
    Process all PR comments sequentially using Claude CLI.

    Iterates through all comments (discussion, review, and inline) and invokes
    Claude to analyze and optionally fix each one. Comments are processed
    one at a time to avoid conflicts.

    Args:
        all_comments: AllComments object containing all comment types
        pr_url: The URL of the PR for context
        working_dir: Optional working directory to run Claude in
        on_progress: Optional callback function called with (index, total, comment)
                     before processing each comment for progress reporting
        on_comment_complete: Optional callback function called with (index, total, comment, result)
                             after processing each comment

    Returns:
        AllCommentsProcessingResult with summary of all processing outcomes

    Raises:
        ClaudeError: If Claude CLI is not available (fails on first invocation)
    """
    comments = all_comments.all_comments
    total = len(comments)

    results: list[tuple["Comment", CommentProcessingResult]] = []
    changes_made_count = 0
    no_changes_count = 0
    error_count = 0

    for i, comment in enumerate(comments):
        # Call progress callback if provided
        if on_progress:
            on_progress(i, total, comment)

        # Process this comment with Claude
        try:
            result = process_comment(comment, pr_url, working_dir)
        except ClaudeError:
            # Re-raise ClaudeError - this typically means Claude CLI is not available
            # and we should stop processing
            raise

        # Track the result
        results.append((comment, result))

        # Call completion callback if provided
        if on_comment_complete:
            on_comment_complete(i, total, comment, result)

        # Update counts
        if result.result == ProcessingResult.CHANGES_MADE:
            changes_made_count += 1
        elif result.result == ProcessingResult.NO_CHANGES_NEEDED:
            no_changes_count += 1
        elif result.result == ProcessingResult.ERROR:
            error_count += 1

    return AllCommentsProcessingResult(
        results=results,
        total_comments=total,
        changes_made_count=changes_made_count,
        no_changes_count=no_changes_count,
        error_count=error_count,
    )


def process_all_comments_with_progress(
    all_comments: "AllComments",
    pr_url: str,
    working_dir: str | None = None,
    verbose: bool = False,
    output: TextIO | None = None,
) -> AllCommentsProcessingResult:
    """
    Process all PR comments with built-in progress reporting.

    This is a convenience function that wraps process_all_comments with a
    ProgressReporter to provide user-friendly output during processing.

    Args:
        all_comments: AllComments object containing all comment types
        pr_url: The URL of the PR for context
        working_dir: Optional working directory to run Claude in
        verbose: If True, include more detailed information in output
        output: Optional output stream (defaults to sys.stdout)

    Returns:
        AllCommentsProcessingResult with summary of all processing outcomes

    Raises:
        ClaudeError: If Claude CLI is not available (fails on first invocation)
    """
    reporter = ProgressReporter(output=output, verbose=verbose)

    # Report start
    reporter.on_start(all_comments.total_count)

    if all_comments.total_count == 0:
        return AllCommentsProcessingResult(
            results=[],
            total_comments=0,
            changes_made_count=0,
            no_changes_count=0,
            error_count=0,
        )

    # Process with progress callbacks
    result = process_all_comments(
        all_comments=all_comments,
        pr_url=pr_url,
        working_dir=working_dir,
        on_progress=reporter.on_comment_start,
        on_comment_complete=reporter.on_comment_complete,
    )

    # Report completion
    reporter.on_complete(result)

    return result
