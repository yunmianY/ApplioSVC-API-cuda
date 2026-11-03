# ApplioSVC-API（CUDA / NVIDIA 版）

面向 [AstrBot](https://github.com/AstrBotDevs/AstrBot) 插件
[`matsuko_cover`](https://github.com/sdfsfsk/matsuko_cover)（AI 点歌 / 翻唱）的**中间层**。

它模仿 [`RVCSVC-API-amd`](https://github.com/sdfsfsk/RVCSVC-API-amd) 的接口形态，但把上游从
**RVC（2333）+ UVR5** 换成了 **Applio（进程内推理）+ UVR5**，并针对 **NVIDIA CUDA** 显卡重写：
不再需要 ROCm / DirectML，也不需要单独启动 RVC WebUI。

```
AstrBot + matsuko_cover
        │  gradio_client(HTTP)
        ├── rvc_base_url ──▶ :3333  ApplioSVC-API（本服务）
        │                        ├── UVR5  人声/伴奏分离
        │                        ├── Applio 音色转换（进程内复用模型）
        │                        └── Pedalboard 后期 + pydub 混音导出 MP3
        └── svc_base_url ──▶ :9999  ApplioSVC-API（SVC 参数契约，同样走 Applio）
```

---

## 与参考方案的对比

| 项目 | 中间层端口 | 上游依赖 | 人声分离 | 备注 |
| --- | --- | --- | --- | --- |
| RVCSVC-API-amd | 3333 / 9999 | RVC 2333 / SVC-Fusion 7777 | UVR5 / HP5 | 仅 AMD ROCm |
| RVCSVC-API-MSST | 3333 / 9999 | RVC 2333 / SVC-Fusion 7777 | BS-Roformer / MSST | 显存需求高 |
| **ApplioSVC-API-cuda（本项目）** | 3333 / 9999 | **Applio（进程内）** | UVR5（5_HP-Karaoke） | **NVIDIA CUDA，无需额外推理服务** |

> 插件端**不需要任何修改**：`/convert`、`/show_model`、`/cache_info`、`/clear_cache`
> 的参数名、返回结构、缓存命中标记都与参考项目一致。

---

## 快速开始

### 1. 环境准备

推荐直接复用 Applio 自带的 Python 环境（已含 torch+cu126、gradio、librosa 等）：

```powershell
..\ApplioV3.6.5\env\python.exe tools\check_env.py
```

输出全部 `[OK]` 即可。若缺少分离模型，执行：

```powershell
..\ApplioV3.6.5\env\python.exe tools\download_models.py
```

也可以双击 `install_env.bat` 自动完成「找 Python → 装依赖 → 下模型」。

### 2. 启动

```powershell
# RVC 兼容网关（插件默认使用这个）
..\ApplioV3.6.5\env\python.exe app_rvc.py

# 或者双击
启动 rvcapi.bat
```

启动后浏览器打开 <http://127.0.0.1:3333/> 可以看到与参考项目类似的界面：
选择音色、填网易云 ID、调升降调/混响，一键翻唱。

#### 启动脚本用的是哪个 Python？

`启动 rvcapi.bat` / `启动 svcapi.bat` 会按顺序自动查找解释器：

1. `..\ApplioV3.6.5\env\python.exe`（当前环境就是这个，Python 3.12.14 + torch 2.7.0+cu126）
2. `..\Applio\env\python.exe`
3. PATH 里的 `python`

所以**不需要手动激活虚拟环境**。如果第 3 步兜底到了系统 Python，通常会因为缺
torch/gradio 直接报导入错误 —— 先跑 `python tools\check_env.py` 就能看出是哪个环境、缺什么。

#### 需要额外装依赖吗？

不需要。Applio 自带的 env 里已经有本项目的全部依赖（gradio 5.49.1、fastapi、
librosa、soundfile、pydub、pedalboard、faiss-cpu、torch+cu126 等），
本项目**没有向该环境安装任何新包**，唯一下载的是 120.9 MB 的人声分离模型
`models/uvr5/5_HP-Karaoke-UVR.pth`。

`install_env.bat` 是给「想从零建环境 / 依赖缺失」的情况准备的：
它会检查 PyTorch，并按 `requirements.txt` 用清华镜像补装依赖，最后下载分离模型。

### 3. 配置 AstrBot 插件

在 AstrBot 后台的 `matsuko_cover` 插件配置里：

| 配置项 | 值 |
| --- | --- |
| `rvc_base_url` | `http://127.0.0.1:3333/` |
| `svc_base_url` | `http://127.0.0.1:9999/`（需要时再启动 `app_svc.py`） |

然后在 QQ 里发 `/点歌 歌名` 即可。

---

## 目录结构

```
ApplioSVC-API-cuda/
├─ app_rvc.py              # 3333 入口（RVC 参数契约）
├─ app_svc.py              # 9999 入口（SVC 参数契约）
├─ app_common.py           # Gradio 界面 + 全部 API 端点
├─ config.json             # 首次运行自动生成
├─ core/
│  ├─ paths.py             # 目录定位（自动找 Applio / ffmpeg）
│  ├─ settings.py          # 配置加载（config.json + APPLIOSVC_* 环境变量）
│  ├─ models.py            # 扫描 .pth、匹配 .index、FAISS 中文路径兼容
│  ├─ engine.py            # Applio 推理封装（进程内复用模型）
│  ├─ separator.py         # UVR5 人声分离封装
│  ├─ downloader.py        # 网易云 ID/链接、直链、本地文件
│  ├─ mixer.py             # EQ/压缩/混响/回声、伴奏变调、混音导出
│  ├─ cache.py             # 分离缓存 + 成品缓存 + 统计清理
│  └─ pipeline.py          # 上面这些的编排
├─ uvr5/                   # UVR5 VR 架构推理代码（第三方，见 NOTICES）
├─ models/uvr5/            # 分离模型权重（下载后放在这里）
├─ tools/
│  ├─ check_env.py         # 环境自检
│  └─ download_models.py   # 下载分离模型
├─ tests/                  # 自测脚本（分离 / 推理 / 流水线 / API 契约）
├─ temp/                   # 成品缓存 + 中间文件
└─ output/uvr5/            # 人声分离缓存
```

### 一次翻唱会在哪些地方留文件

| 位置 | 内容 | 是否自动清理 |
| --- | --- | --- |
| `temp/work/` | 解码后的整首歌 WAV（`netease_<id>.wav` / `local_<hash>.wav`），以及推理中间产物 `<key>_vc.wav` | `_vc.wav` 用完立即删；源 WAV 按 `cache_max_files` 保留最新 |
| `output/uvr5/<源>_<hash>/` | 分离出的 `vocal.wav` + `instrument.wav`（44.1kHz 立体声，约 90MB/首） | 按 `cache_max_files` 保留最新 N 组 |
| `temp/results/` | 最终成品 `<源>_<hash>.mp3` | 同上，这就是命中缓存时直接返回的文件 |
| `temp/netease_login_qr.png` | 扫码登录用的二维码（一次性） | 可手动删 |
| `%TEMP%\appliosvc_api\index\` | FAISS `.index` 的 ASCII 暂存副本（解决中文路径打不开） | 持久，可手动删 |
| `%TEMP%\gradio\<hash>\` | Gradio 对外返回文件时复制的副本（AstrBot 实际下载的就是这里） | **不自动清理**，由 Gradio 自己管 |
| `logs/` | `appliosvc_rvc.log` / `appliosvc_svc.log`（滚动 8MB×3） | 自动滚动 |

想看当前占用：界面里「缓存与服务状态」的 JSON，或调用 `/cache_info`。
要清理：界面按钮，或 `/clear_cache`（scope 可选 `all` / `results` / `separation` / `work`）。

---

## 接口说明

服务与参考项目一样用 Gradio 队列暴露 API（`queue(api_open=True, default_concurrency_limit=1)`）。

### `/convert`

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `song_name_src` | str | 网易云 ID / 分享链接 / 音频直链 / 本地音频路径 |
| `key_shift` | int | 人声升降调（半音，-12~12） |
| `vocal_vol` / `inst_vol` | float | 人声 / 伴奏音量（dB） |
| `model_dropdown` | str | 音色模型文件名（来自 `/show_model`） |
| `reverb_intensity` | float | 混响强度 0~10（4 为默认） |
| `delay_intensity` | float | 回声强度 0~10（0 关闭） |
| `f0_method` | str | `rmvpe` / `fcpe` / `crepe` / `crepe-tiny`；`harvest`、`pm` 会自动回落 `rmvpe` |
| `index_rate` | float | 检索特征占比 0~1 |
| `filter_radius` | int | **兼容保留**，Applio 管线没有对应参数（会自动忽略） |
| `uvr5_agg` | int | 分离强度 0~20 |
| `uvr5_tta` | bool | 分离时开启 TTA（更慢更稳） |
| `uvr5_postprocess` | bool | 分离后处理 |
| `uvr5_window_size` | int | 256 / 512 / 1024 |
| `uvr5_high_end_process` | str | `mirroring` / `none` |
| `msst_batch_size` / `msst_num_overlap` / `msst_normalize` | - | **兼容保留**，UVR5 路线不使用 |
| `vocal_postprocess` | bool | 人声后期：EQ + 压缩 + 混响/回声 |
| `shift_accompaniment` | bool | 伴奏是否跟着升降调（±12 八度除外） |

返回 `(音频文件路径, "true"|"false")`，第二个值是「是否命中缓存」，插件会据此提示。

### 其它端点

| 端点 | 说明 |
| --- | --- |
| `/show_model` | 返回音色模型名列表（`Applio/logs/**/*.pth`，自动排除训练底座） |
| `/cache_info` | 缓存统计（文件数 / 字节数），用于插件与界面展示 |
| `/clear_cache(scope)` | 清理缓存，`scope` ∈ `all` / `results` / `separation` / `work` |
| `/status` | 额外提供：Applio 目录、UVR5 模型、显存、模型数量等诊断信息 |

---

## 配置

首次启动会生成 `config.json`（示例见 `config.example.json`）。常用项：

| 字段 | 默认 | 说明 |
| --- | --- | --- |
| `rvc_port` / `svc_port` | 3333 / 9999 | 监听端口 |
| `applio_dir` | 自动探测 | Applio 安装目录，留空则在同级目录查找 |
| `model_dirs` | `["logs"]` | 相对 `applio_dir` 的模型扫描目录 |
| `extra_model_dirs` | `[]` | 额外的模型目录（绝对路径） |
| `uvr5_model` | `models/uvr5/5_HP-Karaoke-UVR.pth` | 分离模型 |
| `uvr5_device` | `auto` | `auto` / `cuda` / `cpu` |
| `volume_envelope` | 0.25 | Applio 的 rms 混音比（对应 RVC 的 rms_mix_rate） |
| `protect` | 0.33 | 清辅音保护 |
| `max_audio_seconds` | 330 | 超长音频截断，避免单任务跑太久 |
| `output_bitrate` | 320k | 成品 MP3 码率 |
| `cache_max_files` | 200 | 成品/分离缓存各保留的最大数量 |
| `download_sources` | 见示例 | 网易云下载源，`{song_id}` 占位，按顺序尝试 |
| `netease_api_base` | 空 | 自建 NeteaseCloudMusicApi 地址，配了才会走登录态（VIP） |
| `netease_cookie` | 空 | 登录后拿到的 `MUSIC_U=...`，只存在本地配置里 |
| `netease_level` | `exhigh` | 取流音质：`standard` / `higher` / `exhigh` / `lossless` |

也支持环境变量覆盖：`APPLIO_DIR`、`APPLIOSVC_RVC_PORT`、`APPLIOSVC_UVR5_DEVICE`、
`APPLIOSVC_OUTPUT_BITRATE`、`APPLIOSVC_CACHE_MAX_FILES`、`APPLIOSVC_F0_METHOD` 等。

### VIP 歌曲怎么下（需要你自己的账号）

公共外链只对**免费歌曲**有效，VIP 歌会返回一个付费提示页。要下 VIP 歌必须带登录态：

```powershell
# 1. 启动本机网易云 API（需要 Node.js，你已装 node 24）
npx NeteaseCloudMusicApi@4.32.0        # 默认 http://127.0.0.1:3000，保持这个窗口别关

# 2. 扫码登录（脚本会自动生成二维码图片、打开、轮询，成功后把 cookie 写进 config.json）
..\ApplioV3.6.5\env\python.exe tools\netease_qr_login.py

# 3. 验证登录态与取流能力（会打印昵称、VIP 类型，并试取一首 VIP 歌的地址）
..\ApplioV3.6.5\env\python.exe tools\check_netease_login.py 186016

# 4. 重启中间层让新配置生效
```

登录成功后 `config.json` 里会自动出现：

```json
"netease_api_base": "http://127.0.0.1:3000",
"netease_cookie": "MUSIC_U=...; __csrf=...",
"netease_level": "exhigh"
```

> 二维码有效期约 3 分钟；报 `800` 说明过期，重跑脚本即可；手机上**要再点一次确认**（状态 802 → 803）。
> 手动调接口时注意：`key` 就是那串 UUID，**不要带尖括号**，否则二维码里的登录地址是错的。
> PowerShell 5.1 里 `curl` 是 `Invoke-WebRequest` 的别名，想用真 curl 请写 `curl.exe`。

验证通过后重启中间层即可：VIP 歌会优先走登录态接口，免费歌仍然走公共外链兜底。

> ⚠️ **不要把账号密码拼进任何 URL/配置**。登录接口返回的是 cookie，不是可复用的账号密码；
> 把凭据写进链接只会泄露到日志和配置里。`config.json` 已在 `.gitignore` 中，不会被误提交。
> 本项目的 cookie 只用于本地请求，不会写入日志（日志里只出现接口地址）。

**常见现象对照**

| 现象 | 含义 |
| --- | --- |
| `/login/status` 返回 `account: null` | cookie 无效；若刚写入，检查是否混入了 `Path=`、`Max-Age=` 等属性——`normalize_cookie()` 会自动清洗成纯 `k=v; k=v` |
| `/song/url/v1` 返回 `url: null, code: 404` | 该歌**没有版权**（如周杰伦全集），与 VIP 无关，换歌即可 |
| `/song/url/v1` 返回 `url: null, code: 200` | 权限不足（需更高等级 VIP / 数字专辑），可换歌或调整 `netease_level` |


---

## 实现要点（与原版的差异）

1. **不再需要 RVC 2333 服务**：直接用 `rvc.infer.infer.VoiceConverter` 在进程内推理，
   模型只加载一次；切换音色时才重新加载。
2. **工作目录**：Applio 内部大量使用相对路径（`rvc/configs/*.json`、`rvc/models/embedders/contentvec`），
   因此服务启动时会 `chdir` 到 Applio 目录；本项目的所有路径都基于 `__file__` 计算为绝对路径。
3. **FAISS 中文路径兼容**：`faiss.read_index()` 在 Windows 下打不开含中文的路径
   （本项目路径常带中文）。命中索引前会先把 `.index` 硬链接/复制到
   `%TEMP%\appliosvc_api\index\` 这样的纯 ASCII 目录。
4. **人声分离**：移植参考项目使用的 UVR5 VR 架构（`uvr5/`），模型 `5_HP-Karaoke-UVR.pth`，
   与参考实现的行为一致（`agg` / `tta` / `window_size` / `high_end_process` 都生效）。
5. **缓存分两级**：分离缓存（按源音频 + 分离参数）与成品缓存（再加模型、升降调、混响等），
   相同参数重复点歌会秒回，并在进度里标记「缓存命中」。
6. **`filter_radius`、`msst_*`**：保留参数只为接口兼容，实际不参与计算（Applio 管线无对应实现）。
7. **SVC 网关**：`app_svc.py` 用 Applio 模型回放 SVC 的参数契约（`svc_f0_method` 等），
   音色列表同样是 Applio 的 `.pth`；它不是 SVC-Fusion 上游，需要真正的 SVC-Fusion 时请用 `SVCVC-API-SVF`。

---

## 性能参考

测试机：RTX 4060 Laptop 8GB，torch 2.7.0+cu126，35 秒测试音频。

| 阶段 | 冷启动 | 二次（模型已加载） |
| --- | --- | --- |
| UVR5 分离 | ~7 s | 命中分离缓存则 0 s |
| Applio 推理 | ~16 s（含加载模型/HuBERT） | ~5 s |
| 后期 + 混音导出 | ~0.4 s | ~0.4 s |
| **端到端** | ~26 s | **~13 s**（同参数再点则 <1 s） |

---

## 常见问题

**Q：启动报「未能自动定位 Applio 安装目录」**
在 `config.json` 里填 `applio_dir`（绝对路径），或设置环境变量 `APPLIO_DIR`。

**Q：`/show_model` 返回空列表**
检查 `Applio/logs/` 下是否有 `.pth`（训练完成会生成 `<模型名>.pth` 和 `added_*.index`）。
本项目会跳过 `rvc/models/pretraineds/` 里的生成器/判别器权重。

**Q：提示「缺少人声分离模型」**
运行 `python tools/download_models.py`，或手动把 `5_HP-Karaoke-UVR.pth` 放到
`models/uvr5/`。国内网络默认走 `hf-mirror.com` 镜像。

**Q：导出 MP3 失败**
项目根目录或 Applio 目录需要有 `ffmpeg.exe`（Applio 自带）。也可以把 ffmpeg 加入 PATH，
或在 `config.json` 的 `ffmpeg_path` 指定。

**Q：网易云下载失败**
免费歌曲会走官方外链 `music.163.com/song/media/outer/url`，实测可用；**VIP/付费歌曲
拿不到播放地址属于正常现象**（没有账号 Cookie），此时会依次回退 `download_sources`
里的其它公共解析接口。最稳的办法是在插件里把音乐源改成 **QQ 音乐**：插件自己下载好
音频后会把**本地文件路径**传给本服务，本服务原生支持本地文件，不依赖任何第三方解析。
排查时可以先跑一句：

```powershell
..\ApplioV3.6.5\env\python.exe tools\probe_netease_apis.py 2629004781
```

**Q：成品是单声道还是立体声**
Applio 推理输出是单声道人声，本服务会把它上混成立体声后与立体声伴奏混合，
最终导出 44.1kHz / 立体声 / `output_bitrate` 码率的 MP3。

**Q：显存不足 / 想限制占用**
`config.json` 里把 `uvr5_device` 设为 `cpu`（分离会变慢），或关闭 `uvr5_tta`。
推理部分由 Applio 的 `x_pad/x_query` 策略根据显存自动调整。

**Q：端口被占用（`Cannot find empty port in range: 3333-3333`）**
说明已经有一个实例在跑，或者是别的程序占了 3333。新版启动脚本会直接提示占用进程 PID：

```
[ERROR] 端口 3333 已被占用，无法启动（配置里 host=127.0.0.1）
[ERROR] 占用进程 PID=35724
  结束它：taskkill /PID 35724 /F
  或改用其它端口：python app_rvc.py --port 3334
```

改端口时记得同步改插件里的 `rvc_base_url`。另外 `config.json` 里的 `rvc_port` /
`svc_port` 也可以直接改，命令行 `--port` 优先级更高。

**Q：为什么“没装依赖”也能跑？依赖到底装在哪**
Applio 的 `env\` 不是标准 venv（没有 `pyvenv.cfg`），所以 Python 会把**用户级
site-packages** 排在它自己的 `Lib\site-packages` 前面：

```
C:\Users\<你>\AppData\Roaming\Python\Python312\site-packages   ← 实际生效（gradio 5.49.1 / torch 2.7.0+cu126）
<你的 Applio 目录>\env\Lib\site-packages                      ← 被遮蔽（gradio 6.20.0 / torch 2.11.0+cu128）
```

服务启动时会打印 `Gradio <版本> <- <路径>`，方便确认用的是哪一套。**不要在这个环境里
跑 `pip install -U gradio`**，否则会把生效版本换到 6.x；本项目按 Gradio 5 调优。

---

## 自测

```powershell
..\ApplioV3.6.5\env\python.exe tools\check_env.py              # 环境自检
..\ApplioV3.6.5\env\python.exe tests\selftest_separate.py     # 只测人声分离
..\ApplioV3.6.5\env\python.exe tests\selftest_infer.py        # 只测 Applio 推理
..\ApplioV3.6.5\env\python.exe tests\selftest_pipeline.py     # 全流水线 + 缓存命中
..\ApplioV3.6.5\env\python.exe tests\selftest_api.py          # 用 gradio_client 模拟插件调用
..\ApplioV3.6.5\env\python.exe tests\selftest_svc_contract.py # 校验 9999 网关参数契约
..\ApplioV3.6.5\env\python.exe tests\selftest_live.py 2629004781  # 对已启动的服务发真实请求
```

---

## 免责声明

本项目仅用于学习与个人娱乐。生成音频的版权与使用责任由使用者承担；
请勿用于侵犯他人权益的用途。

第三方组件与模型来源见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
