# Git Standards

Team git standard for **IncidentPilot**. Workflow is GitHub (issues + pull requests).

## Permanent Branches

- `main`: Production ready at all times, should **always** work. It only
  contains tested, quality code. No one pushes to `main` directly. Merges from
  `dev` to `main` happen when a slice on `dev` is verified and ready to ship.
- `dev`: Long-lived integration branch until the project is done. All
  individual task branches are created from `dev` and merged back into `dev`.
  Integration checks happen here before merging into `main`.

Task branches are short-lived. Delete them after they merge into `dev`.

## Branch Naming

Every branch must link directly to a GitHub issue. Create the issue first;
the issue number goes in the branch name.

### Branch Naming Format

```text
<issue_num>-<type>/<snake-case-title>
```

Where `<type>` matches your commit type (e.g., feat, fix, docs, refactor, task).

```text
Tasks:         #12-task/add-alert-ingestion
Bug Fixes:     #13-fix/fix-stale-revision-check
Refactoring:   #14-refactor/domain-command-layer
Documentation: #15-docs/add-git-standards
```

**zsh:** `#` starts a comment. Always quote branch names:

```bash
git checkout -b '#1-task/scaffold-fastapi'
git push -u origin '#1-task/scaffold-fastapi'
```

Many branches *can* reference the same issue number if an issue is large.
That is okay; the branch title must describe the specific change.

## Commit Standards

- Commit early and often; no multi-hundred line commits.
- All changes in a commit should be towards a single purpose. (E.g. don't
  partially refactor and partially write documentation.)
- All commits should **compile** / pass the project's basic checks once they exist
  (e.g. lint, unit tests, or `make test` when available).

### Commit Messages

Commit messages must be clear, concise, and describe the changes you made.
All commits must start with one of the following prefixes:

#### Standard Message Types

| Prefix | Use |
| --- | --- |
| `task:` | A specific developer task or component implementation for a feature |
| `feat:` | Code developed for working towards a feature |
| `fix:` | A bug fix |
| `refactor:` | Code improvements, cleanup, or optimization without changing behavior |
| `docs:` | Documentation updates (Markdown files, setup guides, comments) |
| `test:` | Adding or updating test suites |
| `wip:` | Work in Progress (saving progress when the task is not finished) |

Accurately describe your changes in one succinct line.

**Examples:**

```text
- refactor: move transition guards into domain command layer
- fix: reject VALIDATING to MITIGATING state transitions
- docs: add product overview and git standards
- wip: wiring Alertmanager webhook ingress
- test: add stale incident_revision concurrency tests
```

## Empty-repo Bootstrap

`main` cannot exist as a real branch until there is a first commit. That first
commit is the **only** time you commit on `main`. Keep it docs-only so `main`
is never a broken app.

After that, every change goes: issue → task branch from `dev` → PR into `dev`
→ later PR `dev` into `main`.

## Typical Developer Workflow

### 1. Claim your task

- Create or pick a GitHub issue
- Assign yourself
- Add the `In-progress` label if the board uses labels

### 2. Sync your local environment

Before making your branch, make sure you have the latest `dev`:

```bash
git checkout dev
git pull origin dev
```

### 3. Create your task branch

```bash
# Example for issue #42: add TransitionIncident
git checkout -b '#42-task/add-transition-incident'
```

### 4. Code and commit

```bash
git add path/to/files
git commit -m "wip: skeleton TransitionIncident with revision check"
```

Prefer staging specific files over `git add .` when you have unrelated local files.

### 5. Update and rebase

When you are done coding, rebase onto latest `dev` so the PR is clean:

```bash
git checkout dev
git pull origin dev

git checkout '#42-task/add-transition-incident'
git rebase dev
```

If git reports a conflict: open the flagged files, keep the correct code,
`git add` those files, then `git rebase --continue`.

### 6. Push to GitHub

```bash
git push origin '#42-task/add-transition-incident'
```

If you already pushed and then rebased:

```bash
git push --force-with-lease origin '#42-task/add-transition-incident'
```

### 7. Open a pull request

- Create a PR from **your task branch → `dev`** (not into `main`)
- Label the issue `In-Review`
- Describe what changed and why
- Use `Closes #42` (or `Refs #42` if more branches will follow)

### 8. Completing the pull request

- After review, merge into `dev`
- Delete the task branch
- Close the issue (or leave it open if more branches will follow)

### 9. Shipping to production / demo baseline

When `dev` is verified (checks pass, slice works):

- Open a PR from **`dev` → `main`**
- Merge that PR
- Never `git push origin main` with local commits

For IncidentPilot, prefer shipping to `main` when a **verified vertical** is ready
(e.g. first scored bad-deployment demo path), not after every small task.
