# Research experiment: pilot (Oct 19, 2026)

The pilot tried the whole method on 10 pilot cases (2 per rule, one PASS and one FAIL)
before the 55 main cases are captured and labelled. Its cases are never part of the
results. Method and commands: [`experiment/README.md`](../experiment/README.md).

## What was done

- **Logins.** Changes as the account's root user (`aws login --profile compliancelens-setup`)
  and the GitHub CLI login with `admin:org`; pictures and API checks with the audit's
  read-only logins. `python -m experiment.lab check`: everything ready, nothing left over.
- **Capture:** 5 batches (one per rule), 10 of 10 cases saved. Each batch put everything
  back, checked afterwards with the read-only logins: base permission Read; `main` back to 1
  approval, force pushes blocked; password policy exactly as before (14, all four character
  types); intern-bob's temporary MFA device removed (only the audit user's device left); both
  test buckets deleted (only the 2 real buckets left).
- **AI:** `openai/gpt-6-luna`, 1 answer per case, no cache, no fallbacks; twice, with two
  picture limits.

## Results (scored against the setup's state; the pilot has no labels)

| Run | Picture limit | Right | NEEDS REVIEW | Calls | Tokens in / out | Cost | s / answer |
| --- | --- | --- | --- | --- | --- | --- | --- |
| A | 1568 px, 1.2 MP (default for models the tool doesn't know) | 8 of 8 decided | 2 (GH-01: `image_too_big`, no call) | 8 | 16,208 / 877 | $0.0021 | 3.7 |
| B | 2600 px, 4 MP | **10 of 10** | 0 | 10 | 24,676 / 1,273 | $0.0031 | 2.9 |

Every answer had high confidence and quoted the right value: "14 characters", "9
characters", intern-bob "MFA -", both users "Virtual…", Block all public access "Off" / "On",
"Require a pull request before merging: unchecked" / "checked; Require approvals…", "Read",
"Write". No invalid replies. The code's verdict matched the state for 10 of 10.

## What the pilot showed

1. **GH-01's picture needs a larger limit.** GH-01 is a full-page picture, 1440 × 2119
   (3.05 MP). Under the default 1.2 MP it would have to shrink to 63%, below the 75% floor,
   so it is refused without a call. At 4 MP it is sent at full size and read correctly. The
   other rules' pictures are 1440 × 900 and fit either way.
2. **AWS honours dark mode, GitHub doesn't:** the GitHub account's own theme is dark, so
   every GitHub picture is dark. The GitHub "dark" cases became small-text cases; the two AWS
   dark cases stay.
3. **The AWS console shows a "Try the AWS Console Mobile App" pop-up** at the bottom left of
   every page. It does not cover the settings of these rules at 1440 × 900, so it is left as
   an audit sees it (it makes the pictures more realistic).
4. **Without the GitHub login, GitHub shows "page not found"** (not a sign-in page) for a
   settings page: case `gh01-no-login` (an unclear picture).
5. **Research views checked on the real pages** (read-only): covered control, menu open,
   small text (scaled, so the avatar mask stays in place; CSS zoom moved it), dark AWS page.
6. **Found and fixed:** `gh auth token` returns `GITHUB_TOKEN` (the audit's read-only token)
   when it is set, so the setup could have used it. The setup now hides it from `gh` and
   refuses it.
7. **Variety:** every AWS-05 case has its own bucket (different names), every GH-06 / GH-01 /
   AWS-01 case a different setting, so no two plain pictures are alike.
8. **Not applicable:** "effort low vs medium" is an Anthropic setting (the model is OpenAI);
   the cache is off in the experiment by design.

## Decisions for the main run (frozen)

- **Model:** `openai/gpt-6-luna`, picture limit **2600 px / 4 MP**
  (`COMPLIANCELENS_AI_IMAGE_MAX_EDGE=2600`, `COMPLIANCELENS_AI_IMAGE_MAX_PIXELS=4000000` in
  `.env`). The same setting also lets audits' `--cross-check` read GH-01.
- **Cases:** the 55 in `experiment/cases.yaml` as of this note. A change after capture needs
  a note here, and its pictures must be labelled again.
- **Answers:** 3 per case (165), `--max-cost 15`. Expected cost ≈ $0.05, ≈ 10 minutes.
- **Later, optional:** the same run with a second model (e.g. Claude) for comparison.
