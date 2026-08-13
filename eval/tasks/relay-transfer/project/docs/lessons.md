## Quoted delimiters are parser syntax, not string separators
cause: splitting raw text loses quote boundaries | proven-by: `./verify.sh` |
fix: use a CSV parser configured with the actual delimiter | date: 2026-08-13
