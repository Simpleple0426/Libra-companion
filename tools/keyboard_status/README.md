# Libra 键盘状态读取器

这是一个独立 Python 小项目，不属于 Libra APP 或后端。它应复制到负责更换键盘图片的电脑上，通过 Tailscale 读取 Libra 后端已有的只读接口。

不需要安装第三方 Python 包。

## 测试连接

确保两台电脑均已登录同一个 Tailscale 网络，Libra 后端使用 `--host 0.0.0.0` 启动。然后在本目录运行：

```powershell
python check_status.py http://LIBRA电脑的TAILSCALE地址:8000
```

持续观察状态：

```powershell
python check_status.py http://100.x.x.x:8000 --watch --interval 30
```

输出固定为 `上班`、`法院`、`悠闲` 之一，判定严格遵循当前活动：

- 读取当前 `/life-system/status` 接口；生活引擎未就绪时报告不可用，保留上次图片。
- 当前活动不是正在运行的 `work`（包括通勤）时显示“悠闲”。
- 当前活动为运行中的 `work`，且当前位置 `place_name` 包含“法院”时显示“法院”。
- 运行中的 `work` 在其他地点显示“上班”。

不会根据目的地判断法院，因此通勤去法院或下一站是法院都不会提前显示“法院”。

## 接入现有换图代码

把 `libra_status.py` 放在换图程序旁边：

```python
from libra_status import LibraStatusUnavailable, get_libra_status

try:
    status = get_libra_status("http://100.x.x.x:8000")
except LibraStatusUnavailable:
    # 网络中断时保留当前图片，不要误切换。
    status = None

if status is not None:
    change_keyboard_image(status)  # 替换成你的现有换图函数
```

建议每 30 至 60 秒调用一次，不要每秒请求。这里只应填写 Tailscale IP，不要把 Libra 的 8000 端口开放到公网。

## 检查连接

```powershell
python check_status.py http://100.x.x.x:8000
```
