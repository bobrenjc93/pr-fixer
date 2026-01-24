# PR Fixer

A CLI tool that automates addressing PR review comments using Claude AI.

## Overview

**PR Fixer** takes a GitHub PR URL and processes each review comment through Claude AI. For actionable comments (bug fixes, code changes, improvements), Claude automatically makes the fixes and creates commits with descriptive messages. Non-actionable comments (questions, approvals, discussions) are skipped.

The tool is non-destructive — it never pushes changes automatically, allowing you to review all commits before pushing.

## Prerequisites

Before using PR Fixer, ensure you have the following installed and configured:

### 1. Git
```bash
git --version
```

### 2. GitHub CLI (`gh`)
Install and authenticate the GitHub CLI:

```bash
# macOS
brew install gh

# Ubuntu/Debian
sudo apt install gh

# Or see: https://cli.github.com/
```

Then authenticate:
```bash
gh auth login
```

### 3. Claude Code CLI (`claude`)
Install the Claude Code CLI:

```bash
npm install -g @anthropic-ai/claude-code
```

Or see: https://docs.anthropic.com/en/docs/claude-code

## Installation

### From source

Clone the repository and install with [uv](https://docs.astral.sh/uv/):

```bash
git clone https://github.com/your-username/pr-fixer.git
cd pr-fixer
uv sync
```

### Verify installation

```bash
uv run pr-fixer --version
# pr-fixer 0.1.0

uv run pr-fixer --check-deps
# Checks that git, gh, and claude are available
```

## Usage

### Basic Usage

Run from anywhere by specifying the repo directory with `-d`:

```bash
uv run pr-fixer https://github.com/owner/repo/pull/123 -d /path/to/your/repo
```

Or navigate to your local clone and run without `-d`:

```bash
cd /path/to/your/repo
uv run pr-fixer https://github.com/owner/repo/pull/123
```

### What happens

1. **Validates** you're in the correct repository
2. **Checks out** the PR's branch
3. **Fetches** all PR comments (discussion, review summaries, and inline code comments)
4. **Processes** each comment with Claude AI
5. **Creates commits** for any changes Claude makes
6. **Leaves the branch** ready for your review

### Example workflow

```bash
$ uv run pr-fixer https://github.com/owner/my-repo/pull/42 -d ~/projects/my-repo

Processing PR: https://github.com/owner/my-repo/pull/42

Checking out branch: feature/new-widget
Successfully checked out branch: feature/new-widget

Fetching PR comments...
Found 3 comment(s) total.

Found 3 comment(s) to process.

Processing comment 1/3...
  -> Changes made and committed

Processing comment 2/3...
  -> No changes needed

Processing comment 3/3...
  -> Changes made and committed

========================================
Processing complete!
  Total comments: 3
  Changes made: 2
  No changes needed: 1

Done! Created 2 commit(s).
Review the changes and push when ready.
```

After running, check the commits with `git log` and push when satisfied.

## Options

| Option | Description |
|--------|-------------|
| `-d`, `--directory` | Path to the repository (defaults to current directory) |
| `--dry-run` | Show what would happen without making changes |
| `--verbose`, `-v` | Enable verbose output |
| `--skip-checkout` | Skip branch checkout (use current branch instead) |
| `--check-deps` | Check for required dependencies and exit |
| `--version` | Show version number |
| `--help` | Show help message |

### Dry run

Preview which comments would be processed without invoking Claude:

```bash
uv run pr-fixer https://github.com/owner/repo/pull/123 -d /path/to/repo --dry-run
```

### Skip checkout

If you're already on the correct branch:

```bash
uv run pr-fixer https://github.com/owner/repo/pull/123 -d /path/to/repo --skip-checkout
```

### Verbose mode

Get detailed output about each step:

```bash
uv run pr-fixer https://github.com/owner/repo/pull/123 -d /path/to/repo --verbose
```

## How Comments are Processed

PR Fixer fetches three types of comments:

1. **Discussion comments** — General PR discussion
2. **Review summaries** — Comments left with approval/request changes
3. **Inline code comments** — Comments on specific lines of code

For each comment, Claude analyzes whether it's actionable:

**Actionable (Claude makes changes):**
- Bug fix requests
- Code improvement suggestions
- Refactoring requests
- Missing error handling
- Style/formatting issues

**Non-actionable (Claude skips):**
- Questions and discussions
- Approvals ("LGTM", "Looks good")
- General observations
- Already-addressed feedback

When Claude makes changes, it creates a commit with a message like:
```
Address review comment: Fix null pointer exception

Review by @alice on src/widget.js:42:
"This will throw if widget is undefined"

Changes:
- Added null check before accessing widget.props
```

## Troubleshooting

### "Please run this command from within the repository"

Either use the `-d` flag to specify the repository path:
```bash
uv run pr-fixer https://github.com/owner/repo/pull/123 -d /path/to/owner/repo
```

Or navigate to your local clone:
```bash
cd /path/to/owner/repo
uv run pr-fixer https://github.com/owner/repo/pull/123
```

### "Uncommitted changes found"

PR Fixer won't checkout a branch if you have uncommitted changes. Either:
- Commit your changes: `git commit -am "WIP"`
- Stash your changes: `git stash`
- Use `--skip-checkout` if you're already on the right branch

### "gh: command not found"

Install the GitHub CLI:
```bash
brew install gh  # macOS
# or see https://cli.github.com/
```

### "claude: command not found"

Install the Claude Code CLI:
```bash
npm install -g @anthropic-ai/claude-code
```

### "gh: not logged in"

Authenticate with GitHub:
```bash
gh auth login
```

## Development

### Running tests

```bash
uv sync --dev
uv run pytest
```

Run without slow/Claude-dependent tests:
```bash
uv run pytest -m "not slow and not requires_claude"
```

### Project structure

```
pr-fixer/
├── pr_fixer/
│   ├── __init__.py
│   ├── cli.py           # CLI entry point
│   ├── github.py        # GitHub CLI wrapper
│   ├── git.py           # Git operations
│   ├── claude.py        # Claude integration
│   ├── models.py        # Data models
│   └── dependencies.py  # Dependency checking
├── tests/
│   ├── test_github.py
│   ├── test_git.py
│   └── test_integration.py
├── pyproject.toml
└── README.md
```

## License

MIT
