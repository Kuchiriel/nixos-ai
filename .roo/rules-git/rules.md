# Git Workflow Rules

## Conventional Commits
Format: `<type>(<scope>): <subject>`

### Commit Types
- `feat`: New feature — `feat(auth): add OAuth2 login flow`
- `fix`: Bug fix — `fix(payment): resolve timeout on Stripe calls`
- `refactor`: Code refactoring (no behavior change) — `refactor(utils): extract date helpers`
- `docs`: Documentation only — `docs(readme): update installation steps`
- `chore`: Maintenance tasks — `chore(deps): update Node to 20`
- `test`: Tests only — `test(auth): add unit tests for login`
- `style`: Formatting, no logic change — `style: sort imports alphabetically`

### Commit Rules
- Subject max 72 chars
- Imperative mood ("add", not "added")
- No period at end
- Reference issues: `Closes #123`

## Branch Naming
Pattern: `<type>/<short-description>`
- `feature/add-user-dashboard`
- `fix/login-redirect-loop`
- `refactor/extract-user-service`
- `hotfix/security-vulnerability`

Rules: lowercase, hyphens, max 50 chars, delete after merge.

## Agent Git Identity
All AI agent commits use dedicated bot identity:
- Author: m3ta-chiron
- Email: m3ta-chiron@agentmail.to
- SSH key configured via GIT_SSH_COMMAND

## Before Committing
```bash
git var GIT_AUTHOR_IDENT
# Should show: m3ta-chiron <m3ta-chiron@agentmail.to>
```
