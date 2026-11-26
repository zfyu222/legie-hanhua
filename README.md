# LEGIE 简体中文汉化工程

- 游戏名为 LEGIE，汉化标题暂用《军团》。
- 原语言为捷克语。Steam 版提供英语和捷克语界面及字幕。

面向汉化维护与二次开发。玩家可在 [GitHub Releases](https://github.com/zfyu222/legie-hanhua/releases/) 获取补丁及安装说明，v1.1 增补了 Magpie 窗口缩放说明。

## 修改译文

- [正文译文](legie_text_translated.csv)共 722 条，[正文映射](legie_text.mapping.json)记录资源位置和原文 SHA-256。
- [贴图译文](legie_images_text_translated.csv)共 20 条，[贴图映射](legie_images_text.mapping.json)记录对应区域。按现有行序编辑单列 UTF-8 CSV，保留占位符和换行。
- [正文导出校验](TranslateFiles/reports/final_validation.json)记录当前正式译文的哈希。编辑后需重做对应验收，生成与新译文匹配的校验记录。
- [正文术语表](TranslateFiles/glossary/r2/freeze_f76e4e65/built/glossary_reviewed.json)和[贴图术语表](TranslateFiles/image-text/TranslateFiles/glossary/r2/freeze_b7d3f2c3/built/glossary_reviewed.json)供修改时查阅。

## 开发与构建

使用 Windows、Python 3.12、Pillow、fonttools、GNU Binutils 2.42，以及本地的 Noto Sans SC／Noto Serif SC 字体。将仓库克隆到 [StaticHanHua](https://github.com/zfyu222/StaticHanHua) 的 `Projects/legie/`，共用提取器从工作区的 `Tools/localization/` 加载。准备 Steam Build 2445454 原版的 `legie.exe` 与 `legie.sud`，放进 `Game/`。脚本核对原件 SHA-256 后才构建。

```powershell
python patch/restore_source_csv.py legie_text.mapping.json Game
python patch/build.py --destination Build/text --binutils <Binutils目录> --font <字体文件>
```

[原文恢复脚本](patch/restore_source_csv.py)按公开映射从本地 EXE 还原并校验原文 CSV。[原文提取器](extract_text.py)可在独立工作副本走完整提取流程。[构建入口](patch/build.py)和[字形汇编](patch/glyphs.s)生成新 EXE 及 SUD。

[贴图提取](export_images.py)可从本地 SUD 导出图像。完整贴图版构建还需自行按[排版配置](ImageText/texture-styles.json)准备成图清单和贴图原文，向构建入口传入 `--image-patch`。纯文本构建可单独输出到新的测试目录。发布端的[差分生成](Release/build_kit.py)、[安装器](Release/player_patch.ps1)、[离线回放](Release/test_kit.py)使用 xdelta 3.2.2 及脚本所列的本地原件、成品和安装记录。
