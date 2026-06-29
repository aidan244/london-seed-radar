# Claude in Chrome prompt: protect the main branch

Written 2026-06-29. Open github.com/aidan244/london-seed-radar logged in,
then paste everything below the line into Claude in Chrome. The goal is to
protect main from force pushes and deletion without changing the way I push
day to day. This is a solo-maintained PUBLIC repo, so getting the friction
level right matters: read the rules before acting.

---

You are helping me protect the main branch of my GitHub repository
"aidan244/london-seed-radar". I am logged in. Work through the branch
protection settings step by step. Rules first, they override everything:

- Touch only branch protection settings (Settings > Branches, or
  Settings > Rules > Rulesets). Change nothing else: not repository
  visibility, not GitHub Pages, not Actions or workflows, not
  collaborators, not webhooks, not secrets, not the default branch. Never
  push, merge, close, reopen, or delete any branch, PR, commit, or tag.
- Ask me before you save or create each rule, and show me the exact
  settings you are about to apply so I can review them first.
- This repo is maintained by me alone, and I sometimes push directly to
  main. Do NOT enable anything that requires a pull request review or an
  approval before merging, because there is no second person to approve and
  it would lock me out of my own branch. If any setting would stop me
  pushing to or merging into main by myself, stop and ask me before
  enabling it.
- Do not require signed commits (I may not have commit signing set up) and
  do not require status checks unless checks already exist on the repo (see
  step 4). When unsure, leave a setting off and ask me.
- GitHub may offer the newer "Rulesets" or the classic "Branch protection
  rules". Either is fine. Use whichever the page presents and achieve the
  same outcomes below.

What I want protected on main:

- No force pushes: nobody, including me, can rewrite or overwrite main's
  history.
- No deletion: main cannot be deleted.
- Everything else about my workflow stays as it is: I can still push
  commits straight to main.

Steps:

1. Open the repository Settings, then Branches (or Rules > Rulesets if that
   is what GitHub shows). Tell me which of the two interfaces you see.
2. Start a new branch protection rule or ruleset targeting the default
   branch. Set the branch name pattern or target to exactly: main
3. Enable these, and only these, as the core protection:
   - Block force pushes (in classic protection this is "Do not allow force
     pushes", which is on by default once a rule exists; in rulesets it is
     the "Block force pushes" rule). Make sure it is ON.
   - Block deletions ("Do not allow deletions" / "Restrict deletions").
     Make sure it is ON.
   - Optional, ask me first: "Require linear history". Tell me what it
     does and let me decide.
4. Status checks: do not require any unless the repo already has checks
   configured. Check whether any status checks or GitHub Actions exist; if
   none do, skip this and tell me there were none to require. Do not create
   a workflow.
5. Make the protection apply to me too. In classic protection, enable
   "Do not allow bypassing the above settings" (also shown as include
   administrators) so the force push and deletion blocks actually hold for
   the repo owner. In rulesets, leave the bypass list empty. Confirm this
   with me before saving, since it means even I cannot force push to main.
6. Leave these OFF: require a pull request before merging, require
   approvals, require code owner review, require signed commits, require
   deployments. If you think one is worth turning on, describe the
   tradeoff and ask me; do not enable it on your own.
7. Show me the full summary of the rule, then pause. Only save or create it
   after I say yes.
8. After saving, open the rule once more and confirm it is active on main.

Report back in one list: which interface you used (rulesets or classic),
the exact settings now enabled on main, anything you skipped and why
(for example no status checks existed), and any setting you think I should
decide on myself.
