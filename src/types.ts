/**
 * Parsed PR URL information
 */
export interface ParsedPRUrl {
  owner: string;
  repo: string;
  prNumber: number;
}

/**
 * A review comment from a GitHub PR
 */
export interface PRComment {
  id: number;
  body: string;
  path: string;
  line: number | null;
  diffHunk: string;
  user: string;
  createdAt: string;
}

/**
 * Result of processing a comment with Claude
 */
export interface CommentProcessResult {
  commentId: number;
  fixed: boolean;
  commitSha?: string;
  message: string;
}
