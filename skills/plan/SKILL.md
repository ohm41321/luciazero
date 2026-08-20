---
name: plan
description: Build a falsifiable implementation plan for new features, major refactors, ambiguous work, or risky multi-module changes. Use when the user asks for a plan or material choices remain; skip routine edits with clear scope and proof.
---

# Plan

Use the lightest plan that removes uncertainty; do not pause by default.

## 1. Bound the work

State goal/non-goals, modules, public interfaces, and config keys. Separate
assumptions/facts. Inspect repository before trusting guesses.

## 2. Define proof

For every requirement, name an observable pass/fail condition and the command
or inspection that tests it. Never invent exact output. Add the smallest
red-before-green test for missing coverage; include full verification at
closeout.

## 3. Choose reversible steps

Use independently checkable edits; name compatibility risks, data or contract
migrations, rollback points, and unrecoverable state.

## 4. Decide whether to pause

Ask for approval only if ambiguity changes the result or the action is
high-stakes, destructive, changes a public contract, expands scope, deploys,
spends money, or affects production. Ask one decision-shaped question.
Otherwise, show the concise plan and proceed. Update it when evidence changes.
