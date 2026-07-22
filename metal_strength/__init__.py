"""Eurocode steel strength calculator."""

import os

# Our stiffness matrices are small -- a few hundred DOF -- and OpenBLAS spawns
# one thread per core for them by default. The synchronisation costs far more
# than the arithmetic saves: a 330x330 solve measured 0.9 ms on one thread and
# 23-300 ms on sixteen. Set before numpy is imported anywhere, and only if the
# caller has not already chosen; export OPENBLAS_NUM_THREADS yourself to
# override, which is worth doing if you ever solve a genuinely large frame.
for _var in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_var, "1")

__version__ = "0.1.0"
