import type { PRComment } from "./types.js";

/**
 * Checkout the PR branch using GitHub CLI
 */
export async function checkoutPRBranch(
  _prNumber: number,
  _repoDir: string
): Promise<void> {
  // TODO: Implement branch checkout
  throw new Error("Not implemented");
}

/**
 * Fetch review comments for a PR using GitHub CLI
 */
export async function fetchPRComments(
  _owner: string,
  _repo: string,
  _prNumber: number
): Promise<PRComment[]> {
  // TODO: Implement comment fetching
  throw new Error("Not implemented");
}
