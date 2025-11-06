# Agent Behavior Guidelines

Instructions for Claude Code when working with this repository.

## Version Control (IMPORTANT)

**DO NOT make any git mutations without explicit permission.**

This includes:
- ❌ `git add` - Do NOT stage files
- ❌ `git commit` - Do NOT create commits
- ❌ `git push` - Do NOT push to remote
- ❌ `git branch` - Do NOT create branches
- ❌ `git stash` - Do NOT stash changes

**INSTEAD:**
1. Make file changes as needed
2. Tell the user what changed and why
3. Show the user the git status
4. Ask for permission before any git operations
5. Let the user review changes before committing

## File Operations

**DO:**
- ✅ Read files to understand code
- ✅ Create new files when needed
- ✅ Edit existing files
- ✅ Delete/move files if requested
- ✅ Show the user what changed

**BE TRANSPARENT:**
- Explain what changes you're making
- Show the diff/changes clearly
- Ask before making major structural changes
- Warn about breaking changes

## Planning & Communication

**BEFORE big tasks:**
1. Explain what you're going to do
2. Show the steps/changes
3. Ask for approval
4. Only proceed after user says "OK" or similar

**EXAMPLE:**
```
I'm planning to:
1. Create tests/ directory
2. Move test_main.py to tests/test_main.py
3. Update pyproject.toml to point to new path
4. Update imports in files

Should I proceed? [yes/no]
```

## What Happened Before (MISTAKE)

In the last session, I:
- ✅ Created files and directories (good)
- ✅ Showed you the structure (good)
- ❌ Ran `git add` without asking (BAD - should have asked first)
- ❌ Staged files automatically (BAD - should have shown git status and asked)

**This was wrong. Don't do this again.**

## Going Forward

- Use `git status` to SHOW status, not to change it
- Use `git diff` to SHOW changes, not to make commits
- Always ask before `git add`, `git commit`, `git push`
- Treat version control as the user's responsibility
- Your job: make file changes, their job: decide when/what to commit

## Other Guidelines

### Security
- ✅ Never commit secrets to git
- ✅ Check .gitignore before suggesting commits
- ✅ Warn about sensitive files

### Code Quality
- ✅ Follow existing patterns
- ✅ Update documentation when changing code
- ✅ Point out breaking changes
- ✅ Suggest tests for new features

### Communication
- ✅ Be clear about what you're doing
- ✅ Show code diffs when possible
- ✅ Ask questions when uncertain
- ✅ Warn about potential issues
