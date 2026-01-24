import type { ParsedPRUrl } from "./types.js";

/**
 * Parse a GitHub PR URL and extract owner, repo, and PR number
 *
 * Supported formats:
 * - https://github.com/owner/repo/pull/123
 * - https://www.github.com/owner/repo/pull/123
 * - http://github.com/owner/repo/pull/123
 * - With or without trailing slash
 */
export function parsePRUrl(url: string): ParsedPRUrl {
  // Regex pattern to match GitHub PR URLs
  // Captures: owner, repo, and PR number
  const pattern =
    /^https?:\/\/(?:www\.)?github\.com\/([^/]+)\/([^/]+)\/pull\/(\d+)\/?$/;

  const match = url.match(pattern);

  if (!match) {
    throw new Error(
      `Invalid GitHub PR URL: ${url}. Expected format: https://github.com/owner/repo/pull/123`
    );
  }

  const [, owner, repo, prNumberStr] = match;
  const prNumber = parseInt(prNumberStr, 10);

  if (isNaN(prNumber) || prNumber <= 0) {
    throw new Error(`Invalid PR number in URL: ${url}`);
  }

  return {
    owner,
    repo,
    prNumber,
  };
}
