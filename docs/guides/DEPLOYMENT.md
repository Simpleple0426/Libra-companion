# 从零开始部署归然 / Libra（Windows + Android）

这份教程面向没有编程经验的用户。请按顺序操作，不要跳步。完成后，归然后端和 AI 模型运行在 Windows 电脑上，Android 手机通过 Tailscale 连接电脑。

> 使用期间电脑必须开机、联网，并保持后端 PowerShell 窗口运行。电脑睡眠或关机后，手机端暂时无法聊天。

## 0. 需要安装什么

必须安装：

1. **Python**：运行归然后端。
2. **Node.js**：它附带的 `npm` 用来安装 Codex CLI。
3. **Codex CLI**：调用 AI 模型生成回复。
4. **Tailscale**：让手机安全访问电脑。
5. **归然 APK**：安装到 Android 手机。

通常不需要 Flutter、Android Studio、Git 或 VS Code。只有想自行修改和构建 APK 时才需要 Flutter 与 Android Studio。

下文以项目位于 `D:\Guiran` 为例。如果你的路径不同，请替换为真实路径。

## 1. PowerShell 入门

PowerShell 是 Windows 自带的命令窗口，本教程的命令都在这里输入。

1. 按 Windows 键，输入 `PowerShell`。
2. 点击 **Windows PowerShell** 或 **PowerShell**。普通安装无需以管理员身份运行。
3. 复制代码框中的命令，粘贴后按 Enter；不要复制代码框外的反引号。

常用操作：

```powershell
# 查看当前目录
Get-Location

# 进入文件夹；路径含空格时要加引号
cd "D:\Guiran\backend"

# 返回上一级、查看文件、清屏
cd ..
dir
cls
```

如果出现红字，先不要继续，保留完整错误信息进行排查。

## 2. 安装 Python

推荐 Python 3.11 或 3.12 的 64 位版本。

1. 打开 [Python Windows 下载页](https://www.python.org/downloads/windows/)。
2. 下载名称含 `Windows installer (64-bit)` 的安装程序。
3. 双击安装程序，在第一个页面务必勾选 **Add python.exe to PATH**。
4. 点击 **Install Now**，等待完成。
5. 关闭所有 PowerShell 窗口，再重新打开一个窗口。

验证安装：

```powershell
python --version
python -m pip --version
```

应分别显示 Python 和 pip 的版本号。如果 `python` 打开了 Microsoft Store，关闭商店后试：

```powershell
py --version
```

如果只有 `py` 可用，后文命令中的 `python` 可以全部替换成 `py`。

## 3. 安装 Node.js 和 npm

1. 打开 [Node.js 官网](https://nodejs.org/)。
2. 下载 **LTS（长期支持版）** 的 Windows Installer（`.msi`），不要选 Current。
3. 双击安装，保持默认选项；确认 `npm package manager` 和 `Add to PATH` 会被安装。
4. 安装后关闭并重新打开 PowerShell。

验证：

```powershell
node --version
npm --version
```

两行都应输出版本号，具体小版本不同是正常的。

## 4. 安装并登录 Codex CLI

下面的安装与首次登录流程以 [Codex CLI 官方文档](https://learn.chatgpt.com/docs/codex/cli) 为准。

在 PowerShell 安装：

```powershell
npm install -g @openai/codex
```

验证安装：

```powershell
codex --version
```

然后进入项目目录并首次运行 Codex：

```powershell
cd "D:\Guiran"
codex
```

第一次运行时，选择 **Sign in with ChatGPT**（或界面提供的其他登录方式），再按照提示在浏览器中登录并授权。进入 Codex 后输入一句简单内容测试；退出可按 `Ctrl + C`。归然使用这台电脑上的同一份 Codex 登录状态。

> Codex 的可用模型和费用由你的 OpenAI 账户方案决定。不要向别人发送登录文件或账号凭据。

## 5. 下载并解压项目

最适合新手的方法：

1. 在项目 GitHub 页面点击绿色的 **Code**。
2. 点击 **Download ZIP**。
3. 下载后右键 ZIP，选择 **全部解压缩**。
4. 建议解压到简单路径，例如 `D:\Guiran`，尽量避免特殊符号和过长路径。
5. 确认其中能看到 `backend`、`mobile`、`docs` 等文件夹。

如果实际结构是 `D:\Guiran\Libra-main\backend`，后文应使用这个真实路径。从 ZIP 安装不需要 Git。

## 6. 创建虚拟环境并安装依赖

虚拟环境可以避免本项目的 Python 包影响其他软件。打开新 PowerShell，执行：

```powershell
cd "D:\Guiran\backend"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

成功后，命令行开头通常出现 `(.venv)`。如果提示“禁止运行脚本”，执行下面两行：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

这个放行只影响当前窗口，关闭后自动失效。接着安装依赖：

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

下载可能需要几分钟。最后没有红色 `ERROR`，并重新出现命令提示符，通常表示成功。

以后每次重新打开 PowerShell，都需要重新进入目录并激活环境：

```powershell
cd "D:\Guiran\backend"
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

## 7. 创建并配置 `.env`

确保当前目录是 `backend`，执行：

```powershell
New-Item -ItemType Directory -Path ../config -Force
Copy-Item .env.example ../config/.env
notepad ../config/.env
```

基础文字聊天只需确认：

```ini
LIBRA_LLM_PROVIDER=codex
LIBRA_LLM_MODEL=
```

模型留空表示使用 Codex 默认模型，首次部署建议保持留空。其他 API Key 对应语音等可选功能，可暂时全部留空。保存并关闭记事本。

确认文件确实叫 `.env`，而不是 `.env.txt`：

```powershell
Get-Item ../config/.env
```

`.env` 可能含密钥，绝对不要上传或公开。

## 8. 第一次启动后端

确认 PowerShell 行首有 `(.venv)` 且当前目录是 `backend`，执行：

```powershell
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

看到类似下面的内容表示成功：

```text
Uvicorn running on http://0.0.0.0:8000
```

Windows Defender 防火墙首次询问时，允许 Python 访问**专用网络**，无需开放公共网络。保持此窗口打开。

在电脑浏览器访问 `http://127.0.0.1:8000`。如果能看到页面或 JSON 内容，说明电脑本机访问正常。停止后端时在此窗口按 `Ctrl + C`。

## 9. 安装和连接 Tailscale

### 9.1 电脑端

1. 从 [Tailscale Windows 下载页](https://tailscale.com/download/windows) 下载并安装。
2. 打开 Tailscale，在浏览器中完成登录授权。
3. 点击任务栏右下角的 Tailscale 图标，找到本机 IPv4，通常是 `100.x.x.x`。

也可以在 PowerShell 查询：

```powershell
tailscale ip -4
```

记下这个地址。不要使用 `127.0.0.1`、`localhost` 或 `192.168.x.x`。

### 9.2 Android 端

1. 从 Google Play 或 Tailscale 官网安装 Tailscale。
2. 使用与电脑相同的账号登录，或确保两台设备属于同一 Tailnet。
3. 打开连接开关；Android 询问是否允许 VPN 时选择允许。
4. 确认设备列表中电脑和手机都在线。

### 9.3 测试连接

保持后端运行，在手机浏览器输入：

```text
http://100.x.x.x:8000
```

将地址换成电脑真实的 Tailscale IPv4。能看到返回内容，就表示网络已打通。

## 10. 安装 APK 并连接

仓库 `releases` 文件夹若已有发布 APK（例如 `companion-release-20260829.apk`），可直接使用：

1. 用数据线、网盘或聊天软件把 APK 传到手机。
2. 在文件管理器点击 APK。
3. 若提示“禁止安装未知应用”，按提示仅允许当前文件管理器安装，再返回继续。
4. 打开归然，首次连接地址填写 `http://电脑的Tailscale地址:8000`，例如：

```text
http://100.88.12.34:8000
```

5. 点击连接并发送一条文字消息测试。

地址开头必须有 `http://`，末尾必须有 `:8000`。不能填写 `127.0.0.1`。

## 11. 以后每天怎样启动

电脑开机并连接 Tailscale 后，打开 PowerShell，依次执行：

```powershell
cd "D:\Guiran\backend"
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

保持窗口打开，再打开手机 App。结束使用时按 `Ctrl + C`；这只会停止服务，不会删除聊天记录。

## 12. 可选：自行构建 APK

如果使用发布好的 APK，请跳过本节。自行构建需要较大下载量和磁盘空间。

1. 安装 [Git for Windows](https://git-scm.com/download/win)。
2. 安装 [Android Studio](https://developer.android.com/studio)，并通过 SDK Manager 安装 Android SDK、Platform Tools 和 Command-line Tools。
3. 按 [Flutter Windows 安装指南](https://docs.flutter.dev/get-started/install/windows/mobile) 安装 Flutter，并把 Flutter 的 `bin` 目录加入 PATH。
4. 重开 PowerShell，检查环境并接受 Android 许可：

```powershell
flutter doctor
flutter doctor --android-licenses
```

5. 根据 `flutter doctor` 修复 Android 工具问题，然后构建：

```powershell
cd "D:\Guiran\mobile"
flutter pub get
flutter build apk --release
```

生成文件位于：

```text
D:\Guiran\mobile\build\app\outputs\flutter-apk\app-release.apk
```

## 13. 常见问题

### `python` 不是内部或外部命令

重开 PowerShell，再试 `py --version`。如果也失败，重新运行 Python 安装程序，选择 Modify，并确认添加到 PATH。

### `npm` 或 `node` 无法识别

关闭全部 PowerShell 窗口后重开。如果仍失败，重新安装 Node.js LTS，并确认启用了 Add to PATH。

如果 `npm` 存在，但 PowerShell 提示“无法加载文件 npm.ps1，因为在此系统上禁止运行脚本”，只为当前窗口临时放行后重试：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
npm --version
```

### `codex` 无法识别

确认 `npm --version` 正常，再运行：

```powershell
npm install -g @openai/codex
```

然后重开 PowerShell。不要下载来路不明的所谓 Codex 安装包。

### 无法运行 `Activate.ps1`

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

不要为此永久关闭全系统脚本保护。

### Python 依赖安装失败

确认已激活虚拟环境和网络正常，再运行：

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

排错时保留从 `ERROR` 开始的完整输出，不要只截最后一行。

### 端口 8000 已被占用

```powershell
Get-NetTCPConnection -LocalPort 8000 -State Listen
```

通常是后端已在另一个窗口运行。找到原窗口继续使用，或按 `Ctrl + C` 停止后再启动。

### 电脑能打开，手机打不开

检查以下各项：

1. 启动命令包含 `--host 0.0.0.0`。
2. 两端 Tailscale 属于同一 Tailnet 且都在线。
3. 手机填写电脑的 `100.x.x.x` 地址。
4. Windows 防火墙允许 Python 访问专用网络。
5. 先用手机浏览器测试同一地址。

### 手机能连接，但消息发送失败

在 PowerShell 运行 `codex`，确认登录没有过期；确认 `.env` 中为 `LIBRA_LLM_PROVIDER=codex`。修改 `.env` 后必须停止并重启后端。

### 更换电脑或地址

在新电脑重新部署后，把 App 改为新电脑的 Tailscale 地址。若 App 没有修改入口，可清除 App 数据或重新安装。

## 14. 数据和安全

首次启动会在项目根目录 `data/` 创建主数据库。完整存档还包含生活库、消息邮箱、媒体和书库；备份需覆盖整个持久数据范围，不能只复制 `libra.db`。目录与发布方法见[持久数据与发布](PERSISTENT_STORAGE.md)。

不要公开或提交以下内容：

- `config/`
- `data/`
- `backups/`
- `logs/`
- Codex 登录文件、Android 签名文件及任何 API Key

Tailscale 不能替代账号保护，不要把电脑访问权限授予不信任的人。
# 表情包

表情包由后端在启动时从 `mobile/assets/stickers/` 读取。把 `.png`、`.jpg`、`.jpeg`、`.webp` 或 `.gif` 文件直接放入这个目录后，重启后端即可出现在聊天页的表情面板，不需要重新构建 APK。

文件名就是表情含义。若同一含义有多张图，可在文件名末尾加数字，例如 `开心1.jpg`、`开心2.jpg`；应用中会分别显示两张图片，但都标注为“开心”，左然也会按“开心”理解。
