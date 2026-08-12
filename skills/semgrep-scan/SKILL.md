---
name: semgrep-scan
description: Run a comprehensive Semgrep security scan on the codebase, triage findings for true positives, and generate an HTML vulnerability report. Use when the user asks to scan for security vulnerabilities, run SAST, or audit code security.
allowed-tools: Bash, Read, Glob, Grep, Write, Task, TaskCreate, TaskUpdate, TaskList
argument-hint: "[--path <dir>] [--config <ruleset>]"
---

# Semgrep Security Scan

Run a comprehensive Semgrep Pro static analysis scan, triage every finding by reading the source code, and produce an HTML report containing only true-positive vulnerabilities.

## Arguments

- `$ARGUMENTS` (optional): flags such as `--path src/` to limit scope or `--config p/owasp-top-ten` to override the ruleset. Defaults to scanning the entire project with `--config auto`.

## Prerequisites Check

Before scanning, verify the environment:

1. Run `semgrep --pro --version` to confirm Semgrep Pro is installed.
   - If the command fails, inform the user to install Semgrep (`pip install semgrep`), run `semgrep login`, and run `semgrep install-semgrep-pro`.
2. Confirm the project directory exists and contains source files.

If any prerequisite fails, stop and report the issue clearly.

## Step 1 -- Run the Scan

Execute the Semgrep scan and capture results in JSON:

```
semgrep --pro --config auto --json --no-git-ignore <project-dir> 2>nul
```

Apply any overrides from `$ARGUMENTS`:
- If `--path <dir>` is provided, scan only that subdirectory.
- If `--config <ruleset>` is provided, use that instead of `auto`.

Capture the full JSON output for analysis. If the scan returns zero findings, report that the codebase is clean and skip remaining steps.

## Step 2 -- Triage Each Finding

For **every** finding returned by Semgrep:

1. Read the source file at the reported line and surrounding context (at least 10 lines above and below).
2. Trace the data flow: identify where the input originates (user input, HTTP request, file, LLM output, config, etc.) and whether it reaches the sink unsanitized.
3. Evaluate existing mitigations: input validation, sandboxing, allowlists, type checks, framework protections.
4. Classify the finding:
   - **True Positive** -- the vulnerability is real and exploitable, or the mitigation is insufficient / bypassable.
   - **False Positive** -- the code is safe due to effective validation, unreachable code paths, or the rule does not apply in context.
5. For each true positive, assign a severity:
   - **Critical** -- directly exploitable with no effective mitigation, leads to RCE / data breach / auth bypass.
   - **High** -- exploitable but requires specific conditions; single-layer defense that could fail.
   - **Medium** -- defense-in-depth concern; multiple mitigations exist but the pattern is unsafe.
   - **Low** -- informational; best-practice violation with minimal real-world risk.

Be rigorous. Do not inflate severity. Do not dismiss findings without reading the code.

## Step 3 -- Generate the HTML Report

Create a file named `semgrep_report.html` in the project root with the following structure:

### Report Structure

1. **Header**: project name, scan date, Semgrep version.
2. **Summary cards**: rules evaluated, files scanned, total findings, true positives, false positives.
3. **Summary table**: one row per true positive with file, line, severity badge, short description, verdict.
4. **Detailed findings** (one section per true positive, ordered by severity descending):
   - Severity badge and title.
   - File location (path and line number).
   - Semgrep rule ID with link to the rule page.
   - CWE and OWASP tags.
   - Vulnerable code snippet with the dangerous call highlighted.
   - **Analysis**: plain-english explanation of why this is a true positive, how the input reaches the sink, and what mitigations exist or are missing.
   - **Attack vector**: concrete description of how an attacker could exploit this.
   - **Remediation**: specific, actionable fix recommendation with library or code pattern suggestions.
5. **Footer**: scan metadata (engine, config, timestamp).

### Styling Requirements

- Dark theme (GitHub-dark palette).
- Self-contained: all CSS inline in a `<style>` block, no external dependencies.
- Severity color coding: Critical = red, High = orange, Medium = yellow, Low = gray.
- Code snippets in monospace with line numbers.
- Responsive layout.

## Step 4 -- Report to the User

After writing the HTML file, present a concise summary in the chat:

1. A markdown table of true positives (file, line, severity, one-line description).
2. Count of false positives (if any) with brief reasons they were dismissed.
3. The path to the generated HTML report.

## Important Guidelines

- Never skip reading the actual source code. Semgrep results alone are insufficient for triage.
- If a finding is in generated or vendored code, note it but still triage it.
- If the scan produces more than 20 findings, use parallel Task agents to read and triage files concurrently.
- Keep the HTML report deterministic: same findings should produce the same report structure regardless of who runs it.
- Do not modify any source code. This skill is read-only analysis.
