# Setup

- [ ] CI workflow copied from `ci-templates/` to `.github/workflows/ci.yml`, unused
      template removed (see the `infra` repo, `SERVER.md`, "Abhängigkeiten in den
      App-Repos" for the reasoning)

# Before making this repository public

- [ ] **Description** set (shows up in search and on the profile)
- [ ] **Topics** set (3–5, e.g. `python`, `cli`, `automation`)
- [ ] **LICENSE** present and the copyright year is correct
- [ ] **README** complete: purpose, installation, usage
- [ ] **No secrets in the git history** — not just in the working tree:
      `git log -p | grep -iE 'api[_-]?key|token|secret|password'`
- [ ] **Commit emails** are `unstko@users.noreply.github.com`:
      `git log --format='%ae' | sort -u`
- [ ] Issues/Wiki/Projects enabled only if actually used
- [ ] Add the repository to the `PROJECTS` block in the profile README

Delete this file once the project is published.
