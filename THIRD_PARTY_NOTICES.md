# 第三方组件与许可说明

本项目的中间层代码（`app_*.py`、`core/`、`tools/`）遵循参考项目
[RVCSVC-API-amd](https://github.com/sdfsfsk/RVCSVC-API-amd) 的接口约定重写，面向
**Applio + CUDA** 场景。

## 1. uv5/ —— Ultimate Vocal Remover 的 VR 架构推理代码

`uvr5/` 目录来自 UVR5（Ultimate Vocal Remover GUI）的 VR 架构实现，经由
[RVCSVC-API-amd](https://github.com/sdfsfsk/RVCSVC-API-amd) 的 `uvr5/` 目录移植，
仅保留 VR 模型推理所需的最小文件：

- `uvr5/vr.py`
- `uvr5/lib/utils.py`
- `uvr5/lib/name_params.json`
- `uvr5/lib/lib_v5/{nets_61968KB,layers_123821KB,spec_utils,model_param_init}.py`
- `uvr5/lib/lib_v5/modelparams/4band_v2.json`

上游项目：<https://github.com/Anjok07/ultimatevocalremovergui>（MIT License）。
版权归其原作者所有，本项目仅作集成与适配，未修改其算法实现。

## 2. 模型权重（不随仓库分发）

| 文件 | 用途 | 来源 |
| --- | --- | --- |
| `models/uvr5/5_HP-Karaoke-UVR.pth` | 人声/伴奏分离 | UVR5 官方模型（`tools/download_models.py` 从 HF 镜像获取） |
| `ApplioV3.6.5/logs/**/*.pth` | 音色模型 | 你自行训练 / 下载，本项目不附带 |

## 3. 上游依赖

| 组件 | 许可 | 说明 |
| --- | --- | --- |
| [Applio](https://github.com/IAHispano/Applio) | MIT | RVC 系音色转换引擎，本中间层以进程内方式调用 |
| [Gradio](https://github.com/gradio-app/gradio) | Apache-2.0 | 对外暴露与参考项目一致的 `/convert` 队列接口 |
| [Pedalboard](https://github.com/spotify/pedalboard) | GPL-3.0 | 人声后期与伴奏变调效果链 |
| [pydub](https://github.com/jiaaro/pydub) | MIT | 混音与 MP3 导出 |
| [librosa](https://github.com/librosa/librosa) | ISC | 音频读写与 BPM 分析 |
| [FAISS](https://github.com/facebookresearch/faiss) | MIT | 特征检索（Applio 内部使用） |

## 4. 参考项目的接口约定

`/convert`、`/show_model`、`/cache_info`、`/clear_cache` 的参数名与返回结构与
[RVCSVC-API-amd](https://github.com/sdfsfsk/RVCSVC-API-amd) /
[matsuko_cover](https://github.com/sdfsfsk/matsuko_cover) 保持一致，以便 AstrBot 插件
无需修改即可对接。参考项目自身未声明开源许可，因此本项目只复用「接口形态」，
代码为独立实现。
