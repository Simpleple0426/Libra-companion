# Libra Android client

Flutter chat client for the Libra FastAPI backend. For the beginner-friendly deployment guide, read the repository root [README](../README.md).

## 正式版和本地测试版同时安装

同一套源码提供两个 Android flavor：`prod` 保留现有包名
`com.libra.companion.libra_app`，名称为“归然”；`dev` 包名为
`com.libra.companion.libra_app.dev`，名称为“归然·测试”。两个 App 的地址、缓存和权限分别保存。
正式版覆盖更新需要沿用原签名，版本号不得降低；不要卸载正式版来安装测试版。
当前 `app-phone-update.apk` 使用本机 Android debug 签名，而 Gradle release
使用发布签名。此次额外生成的 `app-prod-phone.apk` 使用与该手机更新包一致的
debug 签名，适合原来安装该更新包的手机覆盖安装；`app-prod-release.apk`
不能直接覆盖 debug 签名的安装。后续更新同一安装需继续沿用其签名。
最新安装包另存于项目根目录 `releases/current/`，清理 `mobile/build/`
不会删除这份发布文件。该目录保留 `app-dev-release.apk`、
`app-prod-phone.apk` 和 `app-prod-release.apk`。

VPS 迁移更新使用 build number 2。覆盖安装后会重新确认一次后端地址，
保留旧地址和其他手机数据；验证成功后才保存新地址。
将服务器 `C:\Caddy\libra-app-address.txt` 中的完整私人地址粘贴到连接页，
包括 `/connect/` 后面的随机密钥。私人地址默认隐藏，不应分享或截图。
之后可在首页齿轮 → 个性化设置 → 服务器连接中修改地址。
更新地址同时更新 Android 后台轮询地址。

在 `mobile/` 下运行（Flutter 未加入 PATH 时用 `E:\flutter\bin\flutter.bat`）：

```powershell
flutter build apk --release --flavor dev
flutter build apk --release --flavor prod
```

产物为 `build/app/outputs/flutter-apk/app-dev-release.apk` 和
`build/app/outputs/flutter-apk/app-prod-release.apk`。日常调试用 `flutter run --flavor dev`。
测试版不初始化 Firebase，也不注册 FCM token；保留本地轮询通知。
正式版继续使用现有 `android/app/google-services.json`。

首次打开分别输入 VPS 的 HTTPS 地址和本地电脑局域网地址，例如
`http://192.168.1.100:8000`。手机和电脑需在同一 Wi-Fi，电脑后端监听
`0.0.0.0`，Windows 防火墙仅放行专用网络。无需 Tailscale。
也可用 `--dart-define=LIBRA_API_BASE_URL=地址` 设置首次默认地址；已保存地址优先。

双 APK 只隔离手机数据，后端也必须隔离：正式 VPS 保留原数据和原 Codex 主线程；
本地测试使用独立项目目录、独立 `config/.env`、独立数据目录和独立
`LIBRA_CODEX_HOME`。先完成正式迁移，再准备测试环境，不能清理迁移源。
测试数据可从停机快照复制；仅在确认是测试副本后移除其 `cognition.db` 中
`memory_config` 的 `main_thread_id`、`previous_main_thread_id`、`start_fresh_thread`、
`daily_thread_handoff` 四个会话控制键。其余记忆来源字段不改。
测试 Codex 目录使用新目录并单独登录，不复制正式线程会话；首次测试聊天创建新线程。
不需要历史数据时，使用全新测试数据目录更简单。
如果复制了正式数据库，要清空测试副本的 `push_tokens` 表，避免测试后端向正式 App 推送。

## 旧版 Tailscale 连接方式（可选）

Start FastAPI on the computer so it listens on every interface:

```powershell
cd ..\backend
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

Find the computer's Tailscale IPv4 address (`100.x.x.x`). On the first launch, the app asks for this address and saves it locally.

```powershell
flutter run --flavor dev
```

Both the computer and Android phone must be signed in to the same Tailscale network. Enter the address in the form `http://100.x.x.x:8000` on the connection screen. The source code deliberately contains no usable server address.

## Checks

```powershell
flutter analyze
flutter test
```

## 语音消息与 STT

聊天页点击话筒切换语音模式，按住录音、松开发送。手机上传 WAV 音频，Python 后端使用 Groq Whisper 转写，并通过 librosa 分析音高、能量、停顿和节奏，再把文字与语气交给 Libra。

复制 `backend/.env.example` 中的配置到 `backend/.env`，至少填写 `GROQ_API_KEY`。填写兼容接口的 `LLM_API_KEY` 后会额外启用情绪分类；未填写时仍可转写和聊天。语音文件会保存，点击气泡可回放，长按气泡可查看转写文字。
