#!/usr/bin/env node

import { Command } from "commander";
import { parsePRUrl } from "./parser.js";
import { checkoutPRBranch, fetchPRComments } from "./github.js";
import { processCommentWithClaude } from "./claude.js";

const program = new Command();

program
  .name("pr-fixer")
  .description("CLI tool to automatically fix PR review comments using Claude")
  .version("1.0.0")
  .argument("<pr_url>", "GitHub PR URL to process")
  .option("--dry-run", "Preview without making changes")
  .option("-d, --directory <path>", "Path to the repository directory (defaults to current directory)")
  .action(async (prUrl: string, options: { dryRun?: boolean; directory?: string }) => {
    try {
      const repoDir = options.directory || process.cwd();
      console.log(`Processing PR: ${prUrl}`);
      console.log(`Repository directory: ${repoDir}`);

      // Parse the PR URL
      const { owner, repo, prNumber } = parsePRUrl(prUrl);
      console.log(`Parsed: ${owner}/${repo}#${prNumber}`);

      // Checkout the PR branch
      if (!options.dryRun) {
        await checkoutPRBranch(prNumber, repoDir);
        console.log(`Checked out PR branch`);
      }

      // Fetch PR comments
      const comments = await fetchPRComments(owner, repo, prNumber);
      console.log(`Found ${comments.length} review comments`);

      // Process each comment with Claude
      for (const comment of comments) {
        console.log(`\nProcessing comment by ${comment.user}:`);
        console.log(`  ${comment.body.slice(0, 100)}...`);

        if (!options.dryRun) {
          const result = await processCommentWithClaude(comment);
          if (result.fixed) {
            console.log(`  ✓ Fixed and committed: ${result.commitSha}`);
          } else {
            console.log(`  - No changes needed: ${result.message}`);
          }
        }
      }

      console.log(`\nDone! Review the commits and push when ready.`);
    } catch (error) {
      console.error(
        "Error:",
        error instanceof Error ? error.message : String(error)
      );
      process.exit(1);
    }
  });

program.parse();
