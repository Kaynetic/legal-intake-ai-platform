# Excerpt — constraining an LLM to an auditable decision contract

The chase engine's hardest question isn't technical, it's semantic: *which
"closed" leads are actually worth calling?* In a legal CRM, "closed — no
contact" usually means "we gave up," which is exactly the lead the firm wants
re-engaged; "closed — SOL expired" or "closed — client declined" must never
be called again.

The status engine gives that judgment to Claude on Bedrock, but inside a
strict contract:

## The contract

The model receives **two reconciled sources** — the CRM status + recent
free-text case notes (HTML-stripped), and the platform's own intake database
signals (chat completed? retainer signed? incident type?) — and must return
only:

```json
{
  "disposition": "chase" | "stop" | "paralegal",
  "reason": "<one short, plain-English sentence a non-lawyer can read at a glance>",
  "scenario": "chat_abandoned" | "retainer_abandoned" | "reengage" | null
}
```

- `disposition` drives the automation: `chase` enters the multi-channel
  sequence, `stop` is terminal, `paralegal` routes to a human queue.
- `reason` is shown verbatim in the operations dashboard — the AI must
  justify itself in language the intake team can audit at a glance.
- `scenario` selects the voice/email script variant, so the outreach the
  lead receives matches where they actually dropped off.

## The rules that make it safe

1. **Fail-safe default.** On *any* failure — throttling after retries, bad
   JSON, model unavailable — the record gets `disposition: "paralegal"`.
   An AI failure may pause automation; it must never silently stop (or
   start) a lead's chase.
2. **Policy in the prompt, verbatim.** The chase/stop policy was confirmed
   with the firm's principal and encoded as explicit rules (e.g. "closed
   for no contact is a CHASE, not a stop"), not left to model intuition.
3. **The model decides; flags and gates execute.** A `chase` disposition
   still passes through TCPA-consent checks, statute-of-limitations gating,
   and a human preview/approval step before any call fires.
4. **Escalate what the code shouldn't guess.** Per-state SOL durations are
   a legal question; the system flags them for counsel instead of shipping
   a guessed lookup table.
