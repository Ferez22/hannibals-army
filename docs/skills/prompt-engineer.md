# Skill: Prompt Engineer

> How to write, review, and debug LLM prompts for Hannibal's Army. Used by extractor, ORACLE intent classifier, ORACLE synthesizer, Telegram intent router, summary generator, and any future agent prompt.

## When to use this skill

- Adding a new prompt
- A prompt is returning bad output (hallucinations, format drift, missed entities)
- Switching a prompt from one model to another (Gemma4 ↔ GPT-5.4-mini)
- Reviewing a teammate's prompt before merging

## The principles

### 1. Format follows model

Gemma4:e2b is small. It needs:
- Explicit JSON schema with example values
- `format="json"` Ollama option for structured output
- Numbered rules, not paragraphs
- Examples in the prompt (1-shot or 2-shot) for hard cases

GPT-5.4-mini handles more nuance. Can have:
- Conversational instructions
- Conditional logic ("if X then Y, else Z")
- Multi-turn context
- Less hand-holding on format

**Rule:** when auto-switching between models, prompts are NOT portable. Tune per model or keep them simple enough that both can handle them.

### 2. Define boundaries, not just intent

Bad prompt: "Extract people, teams, and projects."

Good prompt: "Extract entities. Boundaries:
- person: a NAMED human being. NOT 'the speaker', 'the client', generic roles.
- team: subdivision INSIDE a company. NOT the company itself. NOT a job title.
- project: a named initiative/engagement. NOT a todo item, NOT a checklist entry."

For each entity type, name what it is AND what it isn't.

### 3. Give negative examples in the prompt

For Hannibal's Army extractor, the breakthrough was adding contract-specific guidance:
> "If the document is a CONTRACT or AGREEMENT: the SUBJECT of the work IS a project — extract it."

LLMs miss patterns until you tell them the pattern explicitly. Don't assume "intelligent" inference.

### 4. Constrain hallucination with citation requirements

For ORACLE synthesis:
> "Every fact in your answer MUST cite its source. If sources are insufficient: reply EXACTLY 'I don't have enough...'"

Forcing citation kills 80% of hallucination. The "EXACTLY" matters — without it, models paraphrase the no-answer reply and lose detectability.

### 5. JSON output

Always use `format="json"` on Ollama / `response_format={"type": "json_object"}` on OpenAI.

Schema in the prompt:
```
{
  "intent": "person | team | project | ...",
  "needs_clarification": false,
  "suggestions": []
}
```

Then validate against a Pydantic model. Never trust the LLM to follow schema — always validate.

### 6. Retry once on malformed

Pattern in `capabilities/extractor.py`:
```python
parsed = _parse_json(raw)
if parsed is None:
    raw = _call_llm(text, retry=True)  # retry with appended "previous was malformed"
    parsed = _parse_json(raw)
if parsed is None:
    return EMPTY_RESULT  # graceful degradation
```

Don't crash on bad JSON. Don't infinite-retry. One retry with explicit "previous failed" hint, then accept defeat.

### 7. Temperature 0.0 for extraction. ≤0.3 for synthesis.

Extraction needs determinism — same doc should produce same entities run-to-run.
Synthesis can have a little creativity but mostly factual: 0.0–0.3.

### 8. Use placeholder substitution, not f-strings

f-string formatting fights JSON braces in the prompt. Use `.replace("__VAR__", value)` for inserting user input into prompts.

```python
EXTRACTION_PROMPT = """... example: {"key": "..."} ..."""
prompt = EXTRACTION_PROMPT.replace("__DOC_TEXT__", text)
```

This is why we use `__DOC_TEXT__` and `__SOURCES__` everywhere.

## How to review a prompt

Checklist:
- [ ] All entity types have what-it-is AND what-it-isn't
- [ ] At least one example per hard case (contracts, multilingual, ambiguous)
- [ ] Output schema explicit with example values
- [ ] Citation requirement if synthesis
- [ ] "Use ONLY the sources" if synthesis
- [ ] Exact no-answer reply specified if synthesis
- [ ] `format="json"` set on the LLM call if structured
- [ ] Pydantic validation on output
- [ ] One-retry pattern for malformed
- [ ] Temperature 0.0 for extraction, ≤0.3 for synthesis
- [ ] Uses `__PLACEHOLDER__` for input substitution
- [ ] Tested on the extraction spike script for regressions

## How to debug a misbehaving prompt

1. **Capture the raw LLM output.** Add `log.info("raw", extra={"text": raw})` before parsing. Tail `logs/army.log`.
2. **Test in isolation** — copy prompt + doc into `ollama run gemma4:e2b` interactively.
3. **Bisect the prompt** — remove one section at a time, find which rule the model is ignoring.
4. **Test on edge cases** — multilingual docs, very short docs, very long docs, malformed input.
5. **Compare model behavior** — same prompt on Gemma vs cloud. If cloud succeeds and Gemma fails, prompt needs more hand-holding.

## Anti-patterns

| Don't | Why |
|-------|-----|
| Paragraph-style prose with no structure | Small models lose attention mid-paragraph |
| Implicit conventions ("use camelCase for fields") | LLMs ignore unless explicit with example |
| "Be smart" / "Use your judgment" | Means nothing to a 2B-param model |
| Mixing format escape chars (`{`) with `.format()` | Brace conflict, runtime crash |
| Re-using extraction prompts for synthesis | Different goals need different scaffolding |
| Skipping JSON schema validation | Garbage in, garbage downstream |
