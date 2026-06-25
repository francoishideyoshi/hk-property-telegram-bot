Run the full feature pipeline for: $ARGUMENTS

Execute these stages in order. Do not skip ahead. After each stage, confirm the handoff file exists before starting the next.

Delegate to the planner subagent with the feature request above. Wait for .pipeline/spec.md.
If the spec has OPEN QUESTIONS, stop and show them to me. Otherwise delegate to the coder subagent. Wait for .pipeline/changes.md.
Delegate to the tester subagent. Wait for .pipeline/test-results.md. If tests failed, stop and show me the failures.
Delegate to the reviewer subagent. Show me .pipeline/review.md.
Report the final verdict. Do not merge anything. Leave the branch for my morning review.