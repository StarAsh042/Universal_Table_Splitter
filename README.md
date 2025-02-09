# Universal Table Splitter / 通用表格分割器


![Universal_Table_Splitter](https://github.com/user-attachments/assets/929b4a94-fd73-4ae7-8d58-c6e1d19d9c8d)

一款基于Python的跨平台GUI表格分割工具，支持多种文件格式和智能导出选项，自动适应系统主题。

## 功能亮点 ✨
- 📁 **多格式支持**：输入支持 CSV/Excel(xlsx,xls)/JSON/TSV/HTML
- 🎯 **智能分割**：支持自定义行数（1-10000）、灵活编号格式（如`001`生成001,002...）
- 📤 **动态导出**：根据输入文件类型自动过滤可用格式（CSV/XLSX/JSON/TSV/HTML）
- 🌓 **主题适配**：自动检测系统深色/浅色模式
- 🌐 **双语界面**：一键切换中英文，完整错误信息本地化

## 系统依赖 💻
```bash
# 基础依赖
pip install pandas ttkbootstrap openpyxl
# Windows额外需要pywin32
pip install pywin32
```

## 快速开始 🚀
### 安装依赖
```bash
pip install -r requirements.txt
```

### 运行程序
```bash
python splitter.py
```

### 打包为独立EXE
```bash
pyinstaller --onefile --windowed --name "表格分割器" \
--hidden-import "pandas._libs.tslibs.np_datetime" \
--add-data="C:\Python\Lib\site-packages\ttkbootstrap;ttkbootstrap/" \
splitter.py
```

## 使用指南 📖
1. **选择文件**：支持拖放操作，自动识别文件类型
2. **设置参数**：
   - 行数范围：1-10000行
   - 编号格式：使用Python格式字符串（如`03d`生成001,002）
   - 导出格式：根据输入文件动态过滤可用选项
3. **输出目录**：默认使用输入文件所在目录
4. **开始分割**：点击绿色按钮启动任务，实时进度条显示状态

## 常见问题 ❓
**Q：导出Excel时报错？**  
A：请确保已安装openpyxl：`pip install openpyxl`

**Q：界面显示乱码？**  
A：系统需支持中文字体（Windows/Linux默认支持，macOS需安装字体）

**Q：提示"Missing dependency: openpyxl"?**  
A：执行 `pip install openpyxl xlsxwriter html5lib`

**Q：TSV文件导入失败?**  
A：确保文件使用标准制表符分隔，无混合分隔符

**Q：深色模式不生效?**  
A：Windows 10+ / macOS Mojave+ 系统支持最佳

## 贡献指南 🤝
欢迎提交Issues或PR！建议包括：
- 操作系统和Python版本
- 问题重现步骤
- 相关错误截图

## 许可证 📄
本项目基于 [GNU Affero General Public License v3.0](LICENSE) 开源。  
Powered by StarAsh042
