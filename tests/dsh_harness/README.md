# 已迁移至 dshmonitor-test-pack

完整工具链、JSON 用例和运行说明在 [dshmonitor-test-pack](../../dshmonitor-test-pack/README.md)。

```bash
.venv/bin/python dshmonitor-test-pack/run.py test
```

本目录的 `run.py` 仅保留旧命令兼容入口，转发到新的完整回归套件。`VALIDATION.md` 是迁移前单场景的历史记录，不代表本轮结果。新增场景请写入新测试包的 `cases/`。
