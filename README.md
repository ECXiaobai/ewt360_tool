# ewt360_tool

升学e网通 (ewt360) 学习任务自动化工具 — 单文件、零依赖、开箱即用。

> ⚠️ **免责声明**: 本项目仅供学习研究使用，请遵守平台规则与学校规定，使用者自担风险。

## 功能

| 任务类型 | contentType | 处理方式 |
|---------|-------------|---------|
| 视频 | 1 | APP 端 2 倍速心跳刷课（120s 上报 + 60s 等待，实测稳定） |
| 试卷 | 2 | 白卷交卷，直接完成任务 |
| FM 收听 | 3 | `updateMission` 直写 100% |
| 板报 | 5 | `updateMission` 直写 100% |

- 自动识别任务类型，分类处理
- 自动收集全部作业任务（含 FM/板报/试卷）
- 支持 token / 账密两种登录方式
- 终端输出干净：只显示课程名 + 进度

## 依赖

- Python 3.9+
- 仅需 `requests` 一个第三方库（其余为标准库）

```bash
pip install requests
```

## 用法

```bash
# 列任务（含视频/FM/板报/试卷）
python ewt360_tool.py --list

# 一键刷全部未完成任务
python ewt360_tool.py --all

# 刷指定序号任务
python ewt360_tool.py 0 1 2
```

也可以直接下载 Release 里的 `ewt360_brush.exe`（无需 Python 环境）。

### 登录方式（按优先级自动选择）

1. `--token <token>` 命令行直接传
2. `config.yml` 的 `ewt360.access_token`（仓库不包含，自行创建）
3. 同目录 `cred.txt`（第一行账号、第二行密码）
4. 运行时交互输入（token 或账密）

### token 获取

浏览器登录 ewt360 → F12 → Network → 任一请求头 `token` 值（形如 `123456789-1-xxxxxxxxxxxxxxxx`）。

## 配置

复制 `config.example.yml` 为 `config.yml` 使用：

```yaml
ewt360:
  access_token: "你的token"     # 方式一：Token 复用
  account: ""                   # 方式二：账密登录
  password: ""
```

## 项目结构

```
ewt360_tool.py          # 主程序（单文件，全部逻辑）
config.example.yml      # 配置模板
ewt360_brush.exe        # Release 提供（Windows 免 Python）
```

## License

[GPL-3.0](LICENSE) — 使用/修改/再分发请遵守 GPL-3.0 协议。
