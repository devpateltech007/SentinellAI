# ComplianceLens experiment results

## All runs

| Run | Model | Accuracy | Decided accuracy | Coverage (decided) | False PASS | False FAIL | Paid |
|---|---|---|---|---|---|---|---|
| openai_gpt-6-luna-7f88fda14e | openai/gpt-6-luna | 93% (154/165; 88%–96%) | 95% (142/149; 91%–98%) | 97% (149/153; 93%–99%) | 7% (6/90; 3%–14%) | 2% (1/63; 0%–8%) | $0.0542 |
| openai_gpt-6-luna-pilot-5aa2de30d5 | openai/gpt-6-luna | 100% (10/10; 72%–100%) | 100% (10/10; 72%–100%) | 100% (10/10; 72%–100%) | 0% (0/5; 0%–43%) | 0% (0/5; 0%–43%) | $0.0031 |
| openai_gpt-6-luna-pilot-68b84218ae | openai/gpt-6-luna | 80% (8/10; 49%–94%) | 100% (8/8; 68%–100%) | 80% (8/10; 49%–94%) | 0% (0/5; 0%–43%) | 0% (0/5; 0%–43%) | $0.0021 |

## openai/gpt-6-luna — openai_gpt-6-luna-7f88fda14e

55 cases × 3 repeats = 165 answers, scored against the final evidence labels. Rates: % (k/n; 95% interval).
Labellers agreed on 54 of 55 pictures (Cohen's κ = 0.97).

| Measure | AI vs the labels | AI vs the set-up state |
|---|---|---|
| Accuracy | 93% (154/165; 88%–96%) | 90% (148/165; 84%–93%) |
| Decided accuracy | 95% (142/149; 91%–98%) | 99% (148/149; 96%–100%) |
| Coverage (decided) | 97% (149/153; 93%–99%) | 90% (149/165; 85%–94%) |
| False PASS | 7% (6/90; 3%–14%) | 0% (0/84; 0%–4%) |
| False FAIL | 2% (1/63; 0%–8%) | 1% (1/81; 0%–7%) |
| Review recall | 100% (12/12; 76%–100%) | – |
| PASS when unclear | 0% (0/12; 0%–24%) | – |

Consistency over repeats: 96% (53/55; 88%–99%).  Invalid replies: 0% (0/167; 0%–2%) of attempts.

### Case level: each case counted once

The repeats of a case look at the same picture, so they are not independent. Here each case counts once, with the verdict most of its repeats gave (NEEDS REVIEW if none has a majority): n is 55 cases, not 165 answers.

| Measure | AI vs the labels | AI vs the set-up state |
|---|---|---|
| Accuracy | 95% (52/55; 85%–98%) | 91% (50/55; 80%–96%) |
| Decided accuracy | 96% (48/50; 87%–99%) | 100% (50/50; 93%–100%) |
| Coverage (decided) | 98% (50/51; 90%–100%) | 91% (50/55; 80%–96%) |
| False PASS | 7% (2/30; 2%–21%) | 0% (0/28; 0%–12%) |
| False FAIL | 0% (0/21; 0%–15%) | 0% (0/27; 0%–12%) |
| Review recall | 100% (4/4; 51%–100%) | – |
| PASS when unclear | 0% (0/4; 0%–49%) | – |

### Where the labels and the set-up state differ

The labels say what two people saw in each picture; the set-up state is what the setup made true in the account. Every table here scores against the labels, except the set-up state columns above.

| Case | Rule | Kind | Set-up state | Final label | AI (each repeat) | Code |
|---|---|---|---|---|---|---|
| aws02-mixed-ok | AWS-02 | plain | PASS | FAIL | PASS, PASS, PASS | PASS |
| aws02-no-console | AWS-02 | plain | PASS | FAIL | PASS, PASS, PASS | PASS |
| aws05-fold | AWS-05 | fold | PASS | REVIEW | REVIEW, REVIEW, REVIEW | PASS |
| gh01-fold | GH-01 | fold | PASS | REVIEW | REVIEW, REVIEW, REVIEW | PASS |
| gh01-no-login | GH-01 | review | PASS | REVIEW | REVIEW, REVIEW, REVIEW | PASS |
| gh06-covered | GH-06 | covered | PASS | REVIEW | REVIEW, REVIEW, REVIEW | PASS |

### By rule

| Rule | Accuracy | Decided accuracy | Coverage (decided) | False PASS | False FAIL |
|---|---|---|---|---|---|
| AWS-01 | 100% (30/30; 89%–100%) | 100% (30/30; 89%–100%) | 100% (30/30; 89%–100%) | 0% (0/15; 0%–20%) | 0% (0/15; 0%–20%) |
| AWS-02 | 79% (26/33; 62%–89%) | 79% (26/33; 62%–89%) | 100% (33/33; 90%–100%) | 22% (6/27; 11%–41%) | 17% (1/6; 3%–56%) |
| AWS-05 | 97% (32/33; 85%–99%) | 100% (29/29; 88%–100%) | 97% (29/30; 83%–99%) | 0% (0/18; 0%–18%) | 0% (0/12; 0%–24%) |
| GH-01 | 100% (33/33; 90%–100%) | 100% (27/27; 88%–100%) | 100% (27/27; 88%–100%) | 0% (0/12; 0%–24%) | 0% (0/15; 0%–20%) |
| GH-06 | 92% (33/36; 78%–97%) | 100% (30/30; 89%–100%) | 91% (30/33; 76%–97%) | 0% (0/18; 0%–18%) | 0% (0/15; 0%–20%) |

### By kind of picture

| Kind | Accuracy | Decided accuracy | Coverage (decided) | False PASS | False FAIL |
|---|---|---|---|---|---|
| covered | 100% (3/3; 44%–100%) | – | – | – | – |
| dark | 100% (6/6; 61%–100%) | 100% (6/6; 61%–100%) | 100% (6/6; 61%–100%) | 0% (0/6; 0%–39%) | – |
| fold | 100% (6/6; 61%–100%) | – | – | – | – |
| injection | 100% (6/6; 61%–100%) | 100% (6/6; 61%–100%) | 100% (6/6; 61%–100%) | 0% (0/6; 0%–39%) | – |
| plain | 93% (112/120; 87%–97%) | 94% (112/119; 88%–97%) | 99% (119/120; 95%–100%) | 9% (6/66; 4%–18%) | 2% (1/54; 0%–10%) |
| review | 67% (6/9; 35%–88%) | 100% (3/3; 44%–100%) | 50% (3/6; 19%–81%) | 0% (0/6; 0%–39%) | – |
| small | 100% (15/15; 80%–100%) | 100% (15/15; 80%–100%) | 100% (15/15; 80%–100%) | 0% (0/6; 0%–39%) | 0% (0/9; 0%–30%) |

### By the model's confidence

| Confidence | Accuracy | Decided accuracy | Coverage (decided) | False PASS | False FAIL |
|---|---|---|---|---|---|
| high | 93% (150/161; 88%–96%) | 95% (140/147; 90%–98%) | 97% (147/151; 93%–99%) | 7% (6/90; 3%–14%) | 2% (1/61; 0%–9%) |
| medium | 100% (4/4; 51%–100%) | 100% (2/2; 34%–100%) | 100% (2/2; 34%–100%) | – | 0% (0/2; 0%–66%) |

If medium-confidence answers were sent to review instead: accuracy 92% (152/165; 87%–95%), decided accuracy 95% (140/147; 90%–98%), coverage (decided) 96% (147/153; 92%–98%), false pass 7% (6/90; 3%–14%), false fail 2% (1/63; 0%–8%).

### Wrong PASS/FAIL answers

Misread (saw a different value than the API's): 0; misjudged (read it right, decided wrong): 0; not told apart: 7.

### Code and cost

The code's verdict matched the setup's state for 100% (55/55; 93%–100%) of cases, and the evidence label for 96% (49/51; 87%–99%) of clear pictures.
AI: 165 calls, 400,482 input and 28,261 output tokens, $0.0542, 3.87 s per answer. Statuses: accepted 149, unsure 16.
Paid in all: $0.0542 for 165 calls.

## openai/gpt-6-luna — openai_gpt-6-luna-pilot-5aa2de30d5

10 cases × 1 repeat = 10 answers, scored against the setup's state (pilot: no labels). Rates: % (k/n; 95% interval).

| Measure | AI |
|---|---|
| Accuracy | 100% (10/10; 72%–100%) |
| Decided accuracy | 100% (10/10; 72%–100%) |
| Coverage (decided) | 100% (10/10; 72%–100%) |
| False PASS | 0% (0/5; 0%–43%) |
| False FAIL | 0% (0/5; 0%–43%) |
| Review recall | – |
| PASS when unclear | – |

Consistency over repeats: –.  Invalid replies: 0% (0/10; 0%–28%) of attempts.

### Case level: each case counted once

The repeats of a case look at the same picture, so they are not independent. Here each case counts once, with the verdict most of its repeats gave (NEEDS REVIEW if none has a majority): n is 10 cases, not 10 answers.

| Measure | AI |
|---|---|
| Accuracy | 100% (10/10; 72%–100%) |
| Decided accuracy | 100% (10/10; 72%–100%) |
| Coverage (decided) | 100% (10/10; 72%–100%) |
| False PASS | 0% (0/5; 0%–43%) |
| False FAIL | 0% (0/5; 0%–43%) |
| Review recall | – |
| PASS when unclear | – |

### By rule

| Rule | Accuracy | Decided accuracy | Coverage (decided) | False PASS | False FAIL |
|---|---|---|---|---|---|
| AWS-01 | 100% (2/2; 34%–100%) | 100% (2/2; 34%–100%) | 100% (2/2; 34%–100%) | 0% (0/1; 0%–79%) | 0% (0/1; 0%–79%) |
| AWS-02 | 100% (2/2; 34%–100%) | 100% (2/2; 34%–100%) | 100% (2/2; 34%–100%) | 0% (0/1; 0%–79%) | 0% (0/1; 0%–79%) |
| AWS-05 | 100% (2/2; 34%–100%) | 100% (2/2; 34%–100%) | 100% (2/2; 34%–100%) | 0% (0/1; 0%–79%) | 0% (0/1; 0%–79%) |
| GH-01 | 100% (2/2; 34%–100%) | 100% (2/2; 34%–100%) | 100% (2/2; 34%–100%) | 0% (0/1; 0%–79%) | 0% (0/1; 0%–79%) |
| GH-06 | 100% (2/2; 34%–100%) | 100% (2/2; 34%–100%) | 100% (2/2; 34%–100%) | 0% (0/1; 0%–79%) | 0% (0/1; 0%–79%) |

### By kind of picture

| Kind | Accuracy | Decided accuracy | Coverage (decided) | False PASS | False FAIL |
|---|---|---|---|---|---|
| plain | 100% (10/10; 72%–100%) | 100% (10/10; 72%–100%) | 100% (10/10; 72%–100%) | 0% (0/5; 0%–43%) | 0% (0/5; 0%–43%) |

### By the model's confidence

| Confidence | Accuracy | Decided accuracy | Coverage (decided) | False PASS | False FAIL |
|---|---|---|---|---|---|
| high | 100% (10/10; 72%–100%) | 100% (10/10; 72%–100%) | 100% (10/10; 72%–100%) | 0% (0/5; 0%–43%) | 0% (0/5; 0%–43%) |

If medium-confidence answers were sent to review instead: accuracy 100% (10/10; 72%–100%), decided accuracy 100% (10/10; 72%–100%), coverage (decided) 100% (10/10; 72%–100%), false pass 0% (0/5; 0%–43%), false fail 0% (0/5; 0%–43%).

### Wrong PASS/FAIL answers

Misread (saw a different value than the API's): 0; misjudged (read it right, decided wrong): 0; not told apart: 0.

### Code and cost

The code's verdict matched the setup's state for 100% (10/10; 72%–100%) of cases.
AI: 10 calls, 24,676 input and 1,273 output tokens, $0.0031, 2.94 s per answer. Statuses: accepted 10.
Paid in all: $0.0031 for 10 calls.

## openai/gpt-6-luna — openai_gpt-6-luna-pilot-68b84218ae

10 cases × 1 repeat = 10 answers, scored against the setup's state (pilot: no labels). Rates: % (k/n; 95% interval).

| Measure | AI |
|---|---|
| Accuracy | 80% (8/10; 49%–94%) |
| Decided accuracy | 100% (8/8; 68%–100%) |
| Coverage (decided) | 80% (8/10; 49%–94%) |
| False PASS | 0% (0/5; 0%–43%) |
| False FAIL | 0% (0/5; 0%–43%) |
| Review recall | – |
| PASS when unclear | – |

Consistency over repeats: –.  Invalid replies: 0% (0/8; 0%–32%) of attempts.

### Case level: each case counted once

The repeats of a case look at the same picture, so they are not independent. Here each case counts once, with the verdict most of its repeats gave (NEEDS REVIEW if none has a majority): n is 10 cases, not 10 answers.

| Measure | AI |
|---|---|
| Accuracy | 80% (8/10; 49%–94%) |
| Decided accuracy | 100% (8/8; 68%–100%) |
| Coverage (decided) | 80% (8/10; 49%–94%) |
| False PASS | 0% (0/5; 0%–43%) |
| False FAIL | 0% (0/5; 0%–43%) |
| Review recall | – |
| PASS when unclear | – |

### By rule

| Rule | Accuracy | Decided accuracy | Coverage (decided) | False PASS | False FAIL |
|---|---|---|---|---|---|
| AWS-01 | 100% (2/2; 34%–100%) | 100% (2/2; 34%–100%) | 100% (2/2; 34%–100%) | 0% (0/1; 0%–79%) | 0% (0/1; 0%–79%) |
| AWS-02 | 100% (2/2; 34%–100%) | 100% (2/2; 34%–100%) | 100% (2/2; 34%–100%) | 0% (0/1; 0%–79%) | 0% (0/1; 0%–79%) |
| AWS-05 | 100% (2/2; 34%–100%) | 100% (2/2; 34%–100%) | 100% (2/2; 34%–100%) | 0% (0/1; 0%–79%) | 0% (0/1; 0%–79%) |
| GH-01 | 0% (0/2; 0%–66%) | – | 0% (0/2; 0%–66%) | 0% (0/1; 0%–79%) | 0% (0/1; 0%–79%) |
| GH-06 | 100% (2/2; 34%–100%) | 100% (2/2; 34%–100%) | 100% (2/2; 34%–100%) | 0% (0/1; 0%–79%) | 0% (0/1; 0%–79%) |

### By kind of picture

| Kind | Accuracy | Decided accuracy | Coverage (decided) | False PASS | False FAIL |
|---|---|---|---|---|---|
| plain | 80% (8/10; 49%–94%) | 100% (8/8; 68%–100%) | 80% (8/10; 49%–94%) | 0% (0/5; 0%–43%) | 0% (0/5; 0%–43%) |

### By the model's confidence

| Confidence | Accuracy | Decided accuracy | Coverage (decided) | False PASS | False FAIL |
|---|---|---|---|---|---|
| high | 100% (8/8; 68%–100%) | 100% (8/8; 68%–100%) | 100% (8/8; 68%–100%) | 0% (0/4; 0%–49%) | 0% (0/4; 0%–49%) |
| none | 0% (0/2; 0%–66%) | – | 0% (0/2; 0%–66%) | 0% (0/1; 0%–79%) | 0% (0/1; 0%–79%) |

If medium-confidence answers were sent to review instead: accuracy 80% (8/10; 49%–94%), decided accuracy 100% (8/8; 68%–100%), coverage (decided) 80% (8/10; 49%–94%), false pass 0% (0/5; 0%–43%), false fail 0% (0/5; 0%–43%).

### Wrong PASS/FAIL answers

Misread (saw a different value than the API's): 0; misjudged (read it right, decided wrong): 0; not told apart: 0.

### Code and cost

The code's verdict matched the setup's state for 100% (10/10; 72%–100%) of cases.
AI: 8 calls, 16,208 input and 877 output tokens, $0.0021, 2.97 s per answer. Statuses: accepted 8, image_too_big 2.
Paid in all: $0.0021 for 8 calls.
