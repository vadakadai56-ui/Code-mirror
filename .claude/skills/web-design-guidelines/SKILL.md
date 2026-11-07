---
name: web-design-guidelines
description: Review UI code for Web Interface Guidelines compliance. Use when asked to "review my UI", "check accessibility", "audit design", "review UX", or "check my site against best practices".
metadata:
  author: vercel
  version: "1.0.0"
  argument-hint: <file-or-pattern>
  local-modification: "Rules are read from the bundled guidelines.md (pinned copy of vercel-labs/web-interface-guidelines command.md, fetched 2026-11-07) instead of being fetched from the network on every run."
---

# Web Interface Guidelines

Review files for compliance with Web Interface Guidelines.

## How It Works

1. Read the rules from `guidelines.md` in this skill's folder
2. Read the specified files (or prompt user for files/pattern)
3. Check against all rules in the guidelines
4. Output findings in the terse `file:line` format

## Guidelines Source

The rules live in the local, pinned file `guidelines.md` next to this SKILL.md.
Do not fetch them from the network. (Original upstream source:
https://raw.githubusercontent.com/vercel-labs/web-interface-guidelines/main/command.md
— only refresh the local copy if the user asks, and show them the diff first.)

Some rules are written for React/Next.js (`<Link>`, `next/image`, Tailwind classes).
For a plain HTML/CSS/JS project, apply the intent of the rule, and skip rules that
only make sense for those frameworks.

## Usage

When a user provides a file or pattern argument:
1. Read `guidelines.md`
2. Read the specified files
3. Apply all rules from the guidelines
4. Output findings using the format specified in the guidelines

If no files specified, ask the user which files to review.
