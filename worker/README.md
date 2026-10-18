# Draft worker lane (rule-based, stage-only)

Layout:
- worker/draft-assembler.mjs — hook + lead in, staged draft + scores out. Pure Node.
- worker/hooks/<lead>.md — hook file. Needs ## Hook and ## Check sections
  (or hookPara/checkPara inside the lead JSON as fallback).
- worker/leads/<lead>.json — team, fee, praise, subject, followCut, target...
- worker/staged/ — output, git-ignored from main, pushed to review branch only.

The cron workflow assembles every lead with a matching hook, commits the
staged drafts to worker/staged-drafts, and opens a review PR. It never sends
email, spends money, or touches main. Real outreach targets stay local;
only synthetic samples live here.
