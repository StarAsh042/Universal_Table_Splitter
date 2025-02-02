# Universal Table Splitter / 通用表格分割器

![Universal Table Splitter](https://github.com/user-attachments/assets/930ed667-f5a4-4756-8c4e-ce6689b938de)

一款基于Python的跨平台GUI工具，支持将大型表格文件（CSV/Excel/JSON/TSV）按指定行数分割，并导出为多种格式。
自动适应系统深色/浅色主题，支持中英文双语界面。


## 功能亮点 ✨
- 📁 **多格式支持**：输入支持 CSV/Excel(xlsx,xls)/JSON/TSV
- 🎯 **智能分割**：自定义行数、文件编号格式（如`001`, `002`）
- 📤 **灵活导出**：输出格式可选 CSV/Excel/JSON/HTML/TSV
- 🌓 **主题适配**：自动切换深色/浅色模式
- 🌐 **双语切换**：一键切换中英文界面

## 快速开始 🚀
### 安装依赖
```bash
pip install -r requirements.txt
```
运行程序
```bash
python splitter.py
```
打包为独立EXE
```bash
pyinstaller --onefile --windowed --name "表格分割器" \
--hidden-import "pandas._libs.tslibs.np_datetime" \
--add-data="C:\Python\Lib\site-packages\ttkbootstrap;ttkbootstrap/" \
splitter.py
```
## 使用指南 📖
选择文件：点击 "选择输入文件" 按钮导入数据

设置参数：

每份行数（默认1000行）

编号格式（如001生成001,002...）

导出格式（根据输入文件类型自动过滤可用格式）

开始分割：点击绿色按钮启动任务，实时进度条显示状态


## 常见问题 ❓
Q：导出Excel时报错？
A：请确保已安装openpyxl：pip install openpyxl

Q：界面显示乱码？
A：系统需支持中文字体（Windows/Linux默认支持，macOS需安装字体）

## 贡献指南 🤝
欢迎提交Issues或PR！
建议包括：

操作系统和Python版本

问题重现步骤

相关错误截图

Powered by StarAsh042
本项目基于 [GNU Affero General Public License v3.0](LICENSE) 开源。
