---
name: plan
description: Build a falsifiable implementation plan for new features, major refactors, ambiguous work, or risky multi-module changes. Use when the user asks for a plan or material choices remain; skip routine edits with clear scope and proof.
---

# Plan — make the change falsifiable

Use the lightest plan that removes uncertainty. Planning is a design protocol, not a mandatory pause before every edit.

## 1. Bound the work

State the goal, non-goals, affected modules, public interfaces, and configuration keys. Mark assumptions separately from known facts. Inspect the repository before treating a guessed interface or command as real.

## 2. Define proof

For every requirement, name an observable pass/fail condition and the command or inspection that can test it. Do not invent an exact output line before the check exists; define the decisive signal precisely enough that success and failure cannot both satisfy it.

If coverage is missing, plan the smallest red-before-green test or fixture first. Include the full verification tier for closeout.

## 3. Choose reversible steps

Break the work into independently checkable edits. Name compatibility risks, data or contract migrations, rollback points, and any state that cannot be recovered automatically.

## 4. Decide whether to pause

Ask for approval before editing only when the remaining choice is ambiguous and materially changes the result, or when the next action is high-stakes, destructive, changes a public contract, expands scope, deploys, spends money, or affects production. Ask one decision-shaped question.

Otherwise, show the concise plan and proceed. Update it when evidence invalidates a step; do not preserve a stale plan for ceremony.
