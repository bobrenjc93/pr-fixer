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


@dataclass
class CommentGroup:
    """
    A group of inline comments on the same file and line.
    When multiple reviewers comment on the same location, or there's a thread
    of discussion, we group them together for processing as a unit.
    """
    path: str
    line: Optional[int]
    comments: list[InlineComment]
    comment_type: CommentType = CommentType.INLINE

    @property
    def effective_line(self) -> Optional[int]:
        """Return the line number for this group."""
        return self.line

    @property
    def authors(self) -> list[str]:
        """Return list of unique authors in this group."""
        seen = set()
        result = []
        for c in self.comments:
            if c.author not in seen:
                seen.add(c.author)
                result.append(c.author)
        return result

    @property
    def author(self) -> str:
        """Return comma-separated list of authors for compatibility."""
        return ", ".join(self.authors)

    @property
    def body(self) -> str:
        """
        Return combined body of all comments. Each comment is prefixed with
        its author to maintain attribution.
        """
        parts = []
        for c in self.comments:
            parts.append(f"[{c.author}]: {c.body}")
        return "\n\n".join(parts)

    def __str__(self) -> str:
        line_info = f":{self.effective_line}" if self.effective_line else ""
        return f"[InlineGroup] {len(self.comments)} comments on {self.path}{line_info}"


# Type alias for any comment type
Comment = PRComment | ReviewComment | InlineComment | CommentGroup


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
    def all_comments_grouped(self) -> list[Comment]:
        """
        Return all comments with inline comments grouped by (path, line).
        Comments on the same file and line are combined into a CommentGroup.
        Single comments are returned as-is (not wrapped in a group).
        """
        result: list[Comment] = []
        result.extend(self.discussion_comments)
        result.extend(self.review_comments)
        result.extend(self._group_inline_comments())
        return result

    def _group_inline_comments(self) -> list[InlineComment | CommentGroup]:
        """
        Group inline comments by (path, effective_line).
        Returns individual InlineComments if there's only one comment at a location,
        or CommentGroup if there are multiple.
        """
        from collections import defaultdict

        groups: dict[tuple[str, int | None], list[InlineComment]] = defaultdict(list)
        for comment in self.inline_comments:
            key = (comment.path, comment.effective_line)
            groups[key].append(comment)

        result: list[InlineComment | CommentGroup] = []
        for (path, line), comments in groups.items():
            if len(comments) == 1:
                result.append(comments[0])
            else:
                result.append(CommentGroup(path=path, line=line, comments=comments))
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
