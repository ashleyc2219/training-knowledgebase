# Repository Guidelines

## Project Structure & Source of Truth

This repository specifies a self-improving Training Knowledge Base. Application code, dependency manifests, and assets are absent.

- `docs/spec/draft/training-kb-design-doc.md` and `training-kb-erd.md`: current AWS design inputs.
- `docs/spec/erm.dbml`: derived logical data model.
- `docs/spec/features/*.feature`: functional specifications.
- `docs/spec/prompts/`: formulation, discovery, clarification, and design workflows.
- `docs/design/` and `docs/plan/dev-prompts/`: earlier design and development context.
- `tests/unit/` and `tests/integration/`: directories without test files.

Prefer the current AWS specifications when older documents conflict. In particular, `4.design_prompt.md` still contains legacy architecture assumptions. Record unresolved contradictions rather than silently choosing a requirement. The nine logical entities map to one DynamoDB table, one GSI, and S3.

## Build, Test, and Development Commands

Run these from the repository root; Git and ripgrep are required:

```sh
rg --files docs                          # List documentation
rg -n '@Missing|#TODO' docs/spec          # Locate specification gaps
git diff --check                        # Check tracked changes for whitespace errors
git status --short                      # Inspect modified and untracked files
```

No build, startup, formatter, or linter command is configured. Document commands alongside future implementation.

## Style & Naming Conventions

Write specification prose in Traditional Chinese using Taiwan terminology; preserve technical identifiers. Use two-space indentation in DBML and Gherkin. Name features `<中文功能簡稱>.feature`, with one `Feature` per file and atomic `Rule` sections. Use English Gherkin keywords and DataTable column names. Every Example needs a relevant `When` and data assertions. Every DBML table and column needs a note.

## Testing & Specification Validation

Validate specification changes with `@dbml/core` and `@cucumber/gherkin` in isolated tooling; record versions and results. These parsers are not declared dependencies. No test runner, test naming convention, or coverage threshold is configured.

Preserve source references. Rules without source examples retain `@Missing` and `#TODO`; do not invent fixtures to disguise gaps. Parser success establishes syntax, not application behavior.

## Commit & Pull Request Guidelines

The only commit is `b8dd4aa` (`hackathon`); history establishes no recurring convention. Follow the team format: `docs(spec): 補充回饋規則`. Use `<type>(<scope>): <subject>`, subjects within 50 characters, and body lines within 72 characters. Allowed types: `feat|fix|docs|style|refactor|perf|test|chore|revert`. Prefix subjects with issue IDs when applicable.

PR titles use `<type>: <subject>`. Describe purpose, changes, validation, risks, and linked issues in Traditional Chinese. State `尚未執行測試` when applicable; attach screenshots for visible UI changes.

## Agent & Security Guidance

Execute only the requested workflow stage. Preserve unrelated changes and pending deletions. Keep credentials out of files and examples, and label seeded demo metrics explicitly.
