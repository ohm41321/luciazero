#!/usr/bin/env bash
# Remove developer-local hook settings before running repository checks.
# Source this file so the unsets apply to the caller's environment.

while IFS= read -r LZ_VAR; do
  if [ -n "${LZ_VAR}" ]; then unset "${LZ_VAR}"; fi
done < <(env | sed -n 's/^\(LUCIAZERO_[A-Za-z0-9_]*\)=.*/\1/p')
unset LZ_VAR
