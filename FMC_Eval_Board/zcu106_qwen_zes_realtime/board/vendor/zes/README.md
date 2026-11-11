# Licensed ZES EDAC dependency

The vendor header and AArch64 static library are intentionally not stored in
Git. Obtain them from the licensed ZS-EDAC1-LN-03 v1.2 package and place these
exact files in this directory before building the real relay:

| File | Required SHA-256 |
| --- | --- |
| `zesEDAC_LN_AA64_NV_v1.3.0_b01_release.a` | `b8192785cd3466dc491b1eeaf8da8be98bc4fe0a40ff6688d248d3a675be03b4` |
| `zesEdacV130.h` | `1c14e54c4a0545350b28aede434cadbf9076be2e019cc0f5d4ccf554b4129375` |

Run `make verify-vendor` from `board/` before linking. The generated static
relay is also intentionally excluded because it contains linked proprietary
vendor object code.
