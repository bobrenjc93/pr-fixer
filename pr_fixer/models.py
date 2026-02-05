"""Data models for PR comments."""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class CommentType(Enum):
    """Types of PR comments."""
    DISCUSSION = "discussion"
    REVIEW = "review"
    INLINE = "inline"


@dataclass
class PRComment:
    """A discussion comment on a PR (general conversation thread)."""
    author: str
    body: str
    comment_type: CommentType = CommentType.DISCUSSION

    def __str__(self) -> str:
        return f"[Discussion] {self.author}: {self.body[:100]}{'...' if len(self.body) > 100 else ''}"


@dataclass
class ReviewComment:
    """A review summary comment (approve, request changes, comment with body)."""
    author: str
    body: str
    state: str  # e.g., "APPROVED", "CHANGES_REQUESTED", "COMMENTED"
    comment_type: CommentType = CommentType.REVIEW

    def __str__(self) -> str:
        return f"[Review - {self.state}] {self.author}: {self.body[:100]}{'...' if len(self.body) > 100 else ''}"


@dataclass
class InlineComment:
    """An inline code comment on a specific file and line."""
    author: str
    body: str
    path: str  # file path
    line: Optional[int]  # line number (may be None if original_line is used)
    original_line: Optional[int] = None  # original line number before changes
    comment_type: CommentType = CommentType.INLINE

    @property
    def effective_line(self) -> Optional[int]:
        """Return the most relevant line number."""
        return self.line if self.line is not None else self.original_line

    def __str__(self) -> str:
        line_info = f":{self.effective_line}" if self.effective_line else ""
        return f"[Inline] {self.author} on {self.path}{line_info}: {self.body[:80]}{'...' if len(self.body) > 80 else ''}"


# Type alias for any comment type
Comment = PRComment | ReviewComment | InlineComment


@dataclass
class AllComments:
    """Container for all types of PR comments."""
    discussion_comments: list[PRComment]
    review_comments: list[ReviewComment]
    inline_comments: list[InlineComment]

    @property
    def all_comments(self) -> list[Comment]:
        """Return all comments as a flat list."""
        result: list[Comment] = []
        result.extend(self.discussion_comments)
        result.extend(self.review_comments)
        result.extend(self.inline_comments)
        return result

    @property
    def file_comments(self) -> list[InlineComment]:
        """Return only comments associated with specific files (inline comments)."""
        return self.inline_comments

    @property
    def file_comments_count(self) -> int:
        """Return count of comments associated with files."""
        return len(self.inline_comments)

    @property
    def total_count(self) -> int:
        """Return total number of comments across all types."""
        return (
            len(self.discussion_comments)
            + len(self.review_comments)
            + len(self.inline_comments)
        )

    def __str__(self) -> str:
        return (
            f"AllComments(discussion={len(self.discussion_comments)}, "
            f"reviews={len(self.review_comments)}, "
            f"inline={len(self.inline_comments)}, "
            f"total={self.total_count})"
        )
