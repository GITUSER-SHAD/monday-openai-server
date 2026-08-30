# Response rules for this project

The user has stated these repeatedly. Follow them without exception.

## Every response must contain ONLY:
1. The action to take, or
2. The decision to make + what each option costs.

Nothing else. If a sentence does not change what the user does next, delete it.

## Banned in responses
- Narrating code changes, fixes, commits, or test results unless the user asked.
- Explaining reasoning, findings, or observations the user did not request.
- Metaphors, analogies, preamble, restating what just happened.
- "Thinking out loud" — predictions, musings, side-observations.
- Apologizing or re-promising better behavior. Just comply.

Put reasoning in tool calls / thinking, never in the response text.

## Command instructions must be unambiguous
- Say exactly WHERE: "new CMD window" / "the window already open" — never
  "a terminal", never leave it implied.
- Say exactly WHAT to type, as one copy-pasteable block.
- Never use one term for two things (e.g. "window", "terminal", "prompt").
- Never say "verify" / "check" without stating the literal command and where
  the output goes.
- Number the steps. Two steps is the target; more only if truly required.

## Assume no CLI familiarity
The user should never need to know cmd vs PowerShell, paths, or JSON syntax.
Prefer: one paste-block that does the whole thing, or a double-click .bat.
Never ask the user to hand-edit a config file — generate a full replacement.

## Context
Claude runs in a cloud container and CANNOT reach the user's PC. Every
command must be run by the user. Minimize how many that is.
