# CAPABILITY DECOMPOSITION (Ciclo 6)

| Capability | Atomic | 2-step | 3-step | Verify | Failure | Status |
|---|---|---|---|---|---|---|
| read | 3/3 | — | — | — | — | VERIFIED |
| rule application | 3/3 probe | — | 0/9 loop | — | formato | REPRESENTATION (probe) / MODEL (loop) |
| transformation | 3/3 | — | — | — | — | VERIFIED |
| serialization | 3/3 copy | S9 3/3 | — | parse | Python-repr | PARTIAL |
| evidence purity | 3/3 probe | R8 0/3 loop | — | checker | decorações | COMPOSITION-LIMITED |
| verification | 4/4 | — | — | — | — | VERIFIED |
| recovery | — | R8 ação ok | H6 1/3 | mundo | fidelidade | PARTIAL |
| composition | — | H2 3/3 | H5 2/3 | mundo | regra+fidelidade | MODEL-LIMITED |
| planning | — | — | L9 0/12 | checker | attractor+pivot | MODEL-LIMITED |
