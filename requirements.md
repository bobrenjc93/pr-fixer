PR Fixer requirements

The goal of this project is to create a CLI tool pr-fixer that I can run

`pr-fixer <pr_url>` and it will do the following

1) Assume we run it in the repo of the pr url and check out the PR's branch
2) use GitHub cli to get PR comments
3) For each comment
3a) Ask claude programmatically (eg. claude -p) to optionally fix the comment if necessary and then create a commit with a description of the fix and the comment it addressed

That's it! Don't push the branch. Let the user review the code and push if they want. 

So just to confirm the workflow might look as follows for a PR with 3 comments

1) Run `pr-fixer <pr_url>`
2) We checkout the branch of the PR
3) We use GH CLI to get the 3 PR comments
4) We feed the first PR comment into claude, have it fix things and commit (critically claude does the commit, not us!)
5) We feed the second PR comment in claude, claude makes no changes since comment isn't actionable
6) We feed third PR comment in claude, it fixes things and commits
7) Done!

After all of this we should have our original PR branch and 2 commits on top with descriptive comments

In terms of e2e testing, you can use the following PR: https://github.com/pytorch/pytorch/pull/172511 and my local pytorch
checkout /Users/bobren/projects/pytorch.

Here's an example way to use github CLI to get info from a PR. You don't need to use all of it, but your fetching code
should look somewhat similar:

```
{
  echo "=== PR DISCUSSION COMMENTS ==="
  echo

  gh pr view 173218 --json comments \
    | jq -r '.comments[] | "\(.author.login)\n\(.body)\n"'

  echo
  echo "=== REVIEW SUMMARIES ==="
  echo

  gh api repos/:owner/:repo/pulls/173218/reviews \
    | jq -r '.[] | select(.body != "") | "\(.user.login) (\(.state))\n\(.body)\n"'

  echo
  echo "=== INLINE CODE COMMENTS ==="
  echo

  gh api repos/:owner/:repo/pulls/173218/comments \
    | jq -r '.[] | "\(.user.login) on \(.path):\(.line // .original_line)\n\(.body)\n"'
} > pr_173218_all_comments.txt
```
