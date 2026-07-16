# SYN-City — 4-Slide Deck Blueprint

Rule: what's under **ON SLIDE** is ALL the text that slide gets. Everything else is
what you draw or say. Numbers are from the live demo — keep them, judges score reasons.

---

## Slide 1 — Is it a Game, or an Attack — or is it Us?

**ON SLIDE**
- 80M fans. One traffic wave. Three possible truths.
- Fans surging · An attack hiding inside them · Our own code buckling
- Old way: 30 pages tonight — 29 of them are just fans.

**VISUAL** One big traffic spike. Three translucent overlays inside the same spike,
labeled: fans (green), attack (red), fault (amber). A pager icon crossed out.

**SAY** The night of the biggest match ever streamed, everything spikes — so
threshold alerting is useless: it either pages for every goal or misses the botnet
riding inside the merch-drop wave. And sometimes the enemy isn't outside at all — the
load just exposed a bug that was always there. Our system has to tell all three apart,
live, and act.

---

## Slide 2 — Architecture: normal is conditional on context

**ON SLIDE**
- Anomaly ≠ deviation from history. Anomaly = deviation from what tonight *should* look like.
- Telemetry (4 layers) + Context feed (calendar, campaigns, match events, deploys)
- → Detection tree → Constrained LLM reasoning → Governed action → learn & repeat

**VISUAL** Five stacked planes, arrows downward, one feedback arrow returning to the top:
P0 Telemetry (app · orchestration · OS · control plane) | P1 Context feed |
P2 Hierarchical detection tree (binary root → triage → attack / fault leaves) |
P3 LLM reasoning, SOP-constrained, rule-based fallback | P4 Policy-gated action
(gate → 10% rollout → verify → 100% / rollback → audit).

**SAY** The event calendar is a model input, not an annotation: the forecaster knows
the 75th-minute drop is coming, so 4x checkout is inside the expected envelope — same
reading at 3am would alert. A cheap always-on binary root catches every deviation
(worst case is a wrong label, never a missed incident); specialists and the LLM run
only on routed suspects — that's also why it scales. The LLM explains and selects
runbook actions; it never detects. Every action passes a policy gate, rolls out
gradually, verifies fan SLOs, and can undo itself.

---

## Slide 3 — Process: one minute, three verdicts

**ON SLIDE**
- 21:15 — merch drop fires. Checkout 4.1x → **SUPPRESS** (0.93) "expected event traffic"
- 21:15 — logins 8.2x, source entropy collapsed, 61% failures → **ATTACK** (0.91) → rate-limit the cohort
- 21:17 — retries amplify 3.4x, deploy 38 min ago → **FAULT** (0.87) → circuit-break + propose the fix

**VISUAL** A horizontal match-night timeline zoomed on the 75th minute; three decision
cards branching from the same point, color-coded green/red/amber, each with its
confidence badge. Under the fault card: `checkout-svc v2.31 · timeout 200ms → fix`.

**SAY** Same minute, same surge, three different decisions — because volume is never
evidence. The crowd stays statistically human per cohort: diverse sources, coherent
watch-buy behavior. The botnet is a separable population: collapsed entropy,
machine-regular timing, logins that fail and never convert — so we throttle just that
fingerprinted cohort while fans keep flowing. The retry storm traces through the causal
graph to one commit and one config value, and the system proposes the patch. Every
verdict ships with its confidence and a plain-English reason — including the
suppressions.

---

## Slide 4 — Proof: the night, with receipts

**ON SLIDE**
- Closed loop: actions visibly bend the curves — ghost line shows the night *without* us
- MTTR: hours → seconds, measured per incident
- Every decision logged: verdict · confidence · reason · rollback path
- Deterministic replay — bring your own secret scenario

**VISUAL** Dashboard screenshot: KPI charts with envelope band, the attack curve
dropping at action time, a faint "no-intervention" ghost line diverging above it,
decision feed on the right, MTTR counter. Small footer strip of five icons:
demo · RCA reports · action log · architecture+README · this pitch.

**SAY** This isn't a report — it's a replay you can watch and rerun. When the
rate-limit lands you see bot traffic die while checkout keeps climbing; the ghost line
is what tonight would have been without the system — that gap is the MTTR evidence.
Detection is deterministic and seeded, so the judges' secret scenario drops straight
into our config format. And when the AI plane itself is killed mid-replay, detection
and Tier-0 defenses keep running. It suppresses with an explanation, alerts with
evidence, acts with a scalpel — and shows its receipts.
