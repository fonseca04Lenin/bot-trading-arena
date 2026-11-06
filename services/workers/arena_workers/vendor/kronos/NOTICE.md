# Kronos (vendored)

`kronos.py` and `module.py` are the `model/` package of **Kronos: A Foundation Model for the Language of Financial
Markets**. `module.py` is byte-identical to upstream; `kronos.py` differs only in its import header (below).

- Source: https://github.com/shiyu-coder/Kronos, commit `67b630e67f6a18c9e9be918d9b4337c960db1e9a` (2026-04-13)
- Paper: https://arxiv.org/abs/2508.02739
- License: MIT, Copyright (c) 2025 ShiYu. See `LICENSE` in this folder.
- Weights are not in the repo. They are downloaded from Hugging Face at pinned revisions (see
  `strategies/kronos_model.py`): `NeoQuasar/Kronos-small` (MIT) and `NeoQuasar/Kronos-Tokenizer-base` (MIT).

The one change, in `kronos.py`: upstream has `import sys`, `sys.path.append("../")` and `from model.module import *`;
here that is `from .module import *`, so the package imports from inside `arena_workers`. Nothing else uses `sys`.

This folder is excluded from ruff and mypy, so upstream code stays byte-for-byte reviewable against the commit above.
