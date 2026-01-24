import type { PRComment, CommentProcessResult } from "./types.js";

/**
 * Process a single PR comment with Claude
 * Claude will analyze the comment and optionally fix and commit
 */
export async function processCommentWithClaude(
  _comment: PRComment
): Promise<CommentProcessResult> {
  // TODO: Implement Claude invocation
  throw new Error("Not implemented");
}
