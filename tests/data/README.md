# 测试数据目录

本目录用于存放**体积较大、不进版本库**的测试数据（见根目录 `.gitignore` 中的
`tests/data/*.csv` 规则）。目录为空时，相关用例会自动跳过，不影响 `pytest` 的结果。

## 可选数据集：`danbooru_art_full.csv`

`tests/test_integration_danbooru.py` 中的 5 个慢速集成测试需要这个真实数据集
（约 32 MB，419,789 行 × 4 列：`artist, trigger, count, url`）。
它用来验证一些在小样本上看不出来的行为：

- 超过 64 MB 阈值以下的正常路径与流式路径结果一致；
- 流式读取的峰值内存与文件体积无关（`tracemalloc` 断言）；
- 419,789 行分割成 5 个文件后**逐单元格无损**（`DataFrame.equals`）；
- 取消后不留半成品文件、不残留 `.part` 临时文件。

获取方式：把这个文件放到本目录，然后运行

```bash
pytest -m slow -v
```

没有该文件时，这 5 个用例会被标记为 `deselected`（默认 `addopts` 已排除 `slow`），
其余 **197 个用例仍然完整覆盖**所有核心逻辑。
