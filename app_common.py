"""Gradio 中间层：统一实现 RVC(3333) / SVC(9999) 两种接口形态。

接口与 sdfsfsk/RVCSVC-API-amd 保持一致，因此 AstrBot 的 matsuko_cover 插件
无需任何修改即可把 rvc_base_url / svc_base_url 指向本服务。

注意：AstrBot 插件是按 **参数名** 提交 /convert 的（gradio_client.submit(**kwargs)），
因此下面 handle_convert_* 的形参名必须与插件完全一致，不能改成 *_value。
"""

from __future__ import annotations

import argparse
import os
import sys
import traceback
from typing import Any

import gradio as gr

from core import __version__
from core import cache as cache_store
from core.engine import F0_CHOICES
from core.logging_utils import describe_device, get_logger, setup_logging
from core.paths import (
    OUTPUT_DIR,
    PROJECT_DIR,
    TEMP_DIR,
    add_project_to_syspath,
    ensure_runtime_dirs,
    find_ffmpeg,
)
from core.pipeline import ConvertParams, CoverPipeline, PipelineError
from core.settings import Settings, get_settings

log = get_logger("app")

MODE_LABELS = {
    "rvc": ("Applio 翻唱 API（RVC 兼容 · CUDA）", "RVC"),
    "svc": ("Applio 翻唱 API（SVC 兼容 · CUDA）", "SVC"),
}

# 插件会带上这些 MSST 专属参数，本实现（UVR5 路线）接受但不使用
_IGNORED_API_PARAMS = ("msst_batch_size", "msst_num_overlap", "msst_normalize")


def _dropdown_update(**kwargs: Any) -> Any:
    """兼容 Gradio 5 的组件更新方式。"""
    updater = getattr(gr, "update", None)
    if callable(updater):
        return updater(**kwargs)
    return gr.Dropdown(**kwargs)


# ----------------------------------------------------------------------
def _bootstrap(mode: str) -> tuple[Settings, CoverPipeline]:
    """初始化配置、日志、目录与推理后端。"""
    add_project_to_syspath()
    settings = get_settings()
    setup_logging(settings.log_level, filename=f"appliosvc_{mode}.log")
    ensure_runtime_dirs()

    if not settings.ffmpeg_path:
        detected = find_ffmpeg(settings.applio_path)
        if detected:
            settings.ffmpeg_path = detected
            log.info(f"使用 ffmpeg: {detected}")
        else:
            log.warning("未找到 ffmpeg.exe，MP3 导出可能失败（请放到项目根目录或加入 PATH）")

    log.info("=" * 64)
    log.info(f"ApplioSVC-API v{__version__} | 模式 {mode.upper()} | Python {sys.version.split()[0]}")
    log.info(f"项目目录: {PROJECT_DIR}")
    log.info(f"Applio 目录: {settings.applio_path}")
    try:
        import torch

        log.info(f"推理设备: {describe_device(torch)}")
    except Exception as exc:  # pragma: no cover
        log.warning(f"读取显卡信息失败: {exc}")

    pipeline = CoverPipeline(settings)
    # 先把工作目录切到 Applio：其内部 rvc/configs、rvc/models 使用相对路径
    pipeline.engine.activate()
    names = pipeline.refresh_models()
    log.info(f"发现 {len(names)} 个音色模型")
    if not settings.uvr5_model_path().is_file():
        log.warning(f"缺少人声分离模型: {settings.uvr5_model_path()}")
    log.info("=" * 64)
    return settings, pipeline


# ----------------------------------------------------------------------
def _to_params(
    song_name_src: str,
    model_dropdown: str,
    key_shift: float,
    vocal_vol: float,
    inst_vol: float,
    reverb_intensity: float,
    delay_intensity: float,
    f0_method: str,
    index_rate: float,
    filter_radius: float,
    uvr5_agg: float,
    uvr5_tta: bool,
    uvr5_postprocess: bool,
    uvr5_window_size: int,
    uvr5_high_end_process: str,
    vocal_postprocess: bool,
    shift_accompaniment: bool,
    settings: Settings,
) -> ConvertParams:
    def as_int(value: Any, default: int) -> int:
        try:
            return int(round(float(value)))
        except (TypeError, ValueError):
            return default

    def as_float(value: Any, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    return ConvertParams(
        song=str(song_name_src),
        model_name=str(model_dropdown),
        key_shift=as_int(key_shift, 0),
        vocal_vol=as_float(vocal_vol, 0.0),
        inst_vol=as_float(inst_vol, 0.0),
        reverb_intensity=as_float(reverb_intensity, 4.0),
        delay_intensity=as_float(delay_intensity, 0.0),
        f0_method=str(f0_method or settings.default_f0_method),
        index_rate=max(0.0, min(1.0, as_float(index_rate, 0.75))),
        filter_radius=as_int(filter_radius, 3),
        uvr5_agg=as_int(uvr5_agg, settings.uvr5_agg),
        uvr5_tta=bool(uvr5_tta),
        uvr5_postprocess=bool(uvr5_postprocess),
        uvr5_window_size=as_int(uvr5_window_size, settings.uvr5_window_size),
        uvr5_high_end_process=str(uvr5_high_end_process or "mirroring"),
        vocal_postprocess=bool(vocal_postprocess),
        shift_accompaniment=bool(shift_accompaniment),
    )


def build_ui(mode: str, settings: Settings, pipeline: CoverPipeline) -> gr.Blocks:
    title, tag = MODE_LABELS[mode]
    is_svc = mode == "svc"
    default_port = settings.svc_port if is_svc else settings.rvc_port
    initial_models = pipeline.models()
    engine_status = pipeline.engine.status()

    def run_pipeline(params: ConvertParams, progress) -> tuple[str, str, str]:
        """执行流水线并把结果转换成 Gradio 输出。"""
        try:
            outcome = pipeline.convert(params, progress=progress)
        except PipelineError as exc:
            log.error(f"任务失败: {exc}")
            raise gr.Error(str(exc)) from exc
        except Exception as exc:  # 兜底，避免只显示 Internal Error
            log.error(f"未预期的错误: {exc}\n{traceback.format_exc()}")
            raise gr.Error(f"处理失败: {exc}") from exc

        info = (
            f"{'⚡ 缓存命中' if outcome.cache_hit else '✅ 处理完成'}，总耗时 {outcome.elapsed:.1f}s\n"
            f"分离 {outcome.stage_timings.get('separation', 0):.1f}s | "
            f"推理 {outcome.stage_timings.get('inference', 0):.1f}s | "
            f"混音 {outcome.stage_timings.get('mix', 0):.1f}s\n"
            f"输出：{outcome.output_path.name}"
        )
        return str(outcome.output_path), "true" if outcome.cache_hit else "false", info

    # ---------------- API 回调（参数名 = 插件提交名） ----------------
    def handle_convert_rvc(
        song_name_src: str,
        key_shift: float = 0,
        vocal_vol: float = 0,
        inst_vol: float = 0,
        model_dropdown: str = "",
        reverb_intensity: float = 4,
        delay_intensity: float = 0,
        f0_method: str = "rmvpe",
        index_rate: float = 0.75,
        filter_radius: float = 3,
        uvr5_agg: float = 10,
        uvr5_tta: bool = False,
        uvr5_postprocess: bool = False,
        uvr5_window_size: int = 512,
        uvr5_high_end_process: str = "mirroring",
        msst_batch_size: float = 2,
        msst_num_overlap: float = 4,
        msst_normalize: bool = True,
        vocal_postprocess: bool = False,
        shift_accompaniment: bool = True,
        progress: gr.Progress = gr.Progress(),
    ):
        if not song_name_src:
            raise gr.Error("请填写歌曲 ID / 链接或音频路径")
        if not model_dropdown:
            raise gr.Error("请先选择音色模型")
        params = _to_params(
            song_name_src, model_dropdown, key_shift, vocal_vol, inst_vol, reverb_intensity,
            delay_intensity, f0_method, index_rate, filter_radius, uvr5_agg, uvr5_tta,
            uvr5_postprocess, uvr5_window_size, uvr5_high_end_process, vocal_postprocess,
            shift_accompaniment, settings,
        )
        log.info(
            f"收到任务：song={params.song!r} model={params.model_name} key={params.key_shift:+d} "
            f"f0={params.f0_method} index={params.index_rate:.2f} agg={params.uvr5_agg} "
            f"tta={params.uvr5_tta} vocal_fx={params.vocal_postprocess} "
            f"(msst 参数已忽略: {msst_batch_size}/{msst_num_overlap}/{msst_normalize})"
        )
        return run_pipeline(params, progress)

    def handle_convert_svc(
        song_name_src: str,
        key_shift: float = 0,
        vocal_vol: float = 0,
        inst_vol: float = 0,
        model_dropdown: str = "",
        reverb_intensity: float = 4,
        delay_intensity: float = 0,
        uvr5_agg: float = 10,
        uvr5_tta: bool = False,
        uvr5_postprocess: bool = False,
        uvr5_window_size: int = 512,
        uvr5_high_end_process: str = "mirroring",
        msst_batch_size: float = 2,
        msst_num_overlap: float = 4,
        msst_normalize: bool = True,
        vocal_postprocess: bool = False,
        shift_accompaniment: bool = True,
        svc_f0_method: str = "rmvpe",
        progress: gr.Progress = gr.Progress(),
    ):
        if not song_name_src:
            raise gr.Error("请填写歌曲 ID / 链接或音频路径")
        if not model_dropdown:
            raise gr.Error("请先选择音色模型")
        params = _to_params(
            song_name_src, model_dropdown, key_shift, vocal_vol, inst_vol, reverb_intensity,
            delay_intensity, svc_f0_method, 0.75, 3, uvr5_agg, uvr5_tta, uvr5_postprocess,
            uvr5_window_size, uvr5_high_end_process, vocal_postprocess, shift_accompaniment,
            settings,
        )
        log.info(
            f"[SVC 网关] 收到任务：song={params.song!r} model={params.model_name} "
            f"key={params.key_shift:+d} f0={params.f0_method}(svc_f0_method)"
        )
        return run_pipeline(params, progress)

    # ---------------- 界面 ----------------
    with gr.Blocks(title=title, theme=gr.themes.Soft()) as app:
        gr.Markdown(
            f"# {title}\n"
            f"**{tag} 接口 · 端口 {default_port}** | Applio + UVR5 | "
            f"设备：{engine_status.get('device', '未知')}\n\n"
            "> 供 AstrBot 插件 `matsuko_cover` 调用；请勿把 3333 / 9999 直接暴露到公网。"
        )

        with gr.Row():
            with gr.Column(scale=3):
                with gr.Row():
                    model_dropdown = gr.Dropdown(
                        label="AI 音色模型",
                        choices=initial_models,
                        value=(initial_models[0] if initial_models else None),
                        interactive=True,
                        allow_custom_value=True,
                    )
                    refresh_btn = gr.Button("🔄 刷新列表", size="sm")
                    switch_btn = gr.Button("✨ 加载音色", size="sm", variant="primary")
                model_status = gr.Textbox(label="模型状态", value="尚未加载模型", interactive=False)

                song_input = gr.Textbox(
                    label="歌曲来源",
                    placeholder="网易云歌曲 ID / 链接，或本地音频文件路径",
                    info="插件在网易云模式传 ID，在 QQ 音乐模式传本地文件路径",
                )
                key_shift_in = gr.Slider(-12, 12, value=0, step=1, label="人声升降调", info="单位：半音")
                with gr.Row():
                    vocal_vol_in = gr.Slider(-3, 3, value=0, step=0.5, label="人声音量(dB)")
                    inst_vol_in = gr.Slider(-3, 3, value=0, step=0.5, label="伴奏音量(dB)")
                with gr.Row():
                    reverb_in = gr.Slider(0, 10, value=4, step=0.5, label="混响强度")
                    delay_in = gr.Slider(0, 10, value=0, step=0.5, label="回声强度")

                with gr.Accordion("高级参数", open=False):
                    with gr.Row():
                        f0_in = gr.Dropdown(
                            F0_CHOICES,
                            value=(settings.default_f0_method
                                   if settings.default_f0_method in F0_CHOICES else "rmvpe"),
                            label="音高提取算法",
                        )
                        index_rate_in = gr.Slider(0, 1, value=0.75, step=0.05, label="检索特征占比")
                        filter_radius_in = gr.Slider(0, 7, value=3, step=1, label="滤波半径（兼容保留）")
                    with gr.Row():
                        uvr5_agg_in = gr.Slider(0, 20, value=settings.uvr5_agg, step=1, label="分离强度 agg")
                        uvr5_window_in = gr.Dropdown(
                            [256, 512, 1024], value=settings.uvr5_window_size, label="窗口大小"
                        )
                        uvr5_high_end_in = gr.Dropdown(
                            ["mirroring", "none"], value=settings.uvr5_high_end_process, label="高频处理"
                        )
                    with gr.Row():
                        uvr5_tta_in = gr.Checkbox(value=settings.uvr5_tta, label="分离 TTA（更慢更稳）")
                        uvr5_post_in = gr.Checkbox(value=settings.uvr5_postprocess, label="分离后处理")
                        vocal_fx_in = gr.Checkbox(value=False, label="人声后期（EQ/压缩/混响）")
                        shift_inst_in = gr.Checkbox(value=True, label="伴奏同步升降调")

                run_btn = gr.Button("🎤 开始翻唱", variant="primary", size="lg")

            with gr.Column(scale=2):
                audio_out = gr.Audio(label="成品试听", type="filepath", interactive=False)
                result_info = gr.Textbox(label="处理信息", interactive=False, lines=5)
                with gr.Accordion("缓存与服务状态", open=False):
                    cache_json = gr.JSON(label="缓存统计")
                    with gr.Row():
                        cache_scope = gr.Dropdown(
                            ["all", "results", "separation", "work"], value="all", label="清理范围"
                        )
                        clear_btn = gr.Button("🧹 清理缓存")
                    status_json = gr.JSON(label="服务状态")

        gr.Markdown(
            "### 说明\n"
            "- 本中间层用 **Applio** 做音色转换（替代 RVC 2333 服务），用 **UVR5** 做人声分离。\n"
            "- 分离结果与最终成品都会缓存，相同参数重复请求直接返回（日志标记 cache hit）。\n"
            "- 生成音频仅供学习与个人娱乐，请勿用于侵权用途。"
        )

        # ---------------- 隐藏的 API 组件（与参考项目对齐） ----------------
        api_model_name = gr.Textbox(visible=False)
        api_f0_method = gr.Dropdown(
            choices=F0_CHOICES + ["harvest", "pm"], value="rmvpe", visible=False
        )
        api_index_rate = gr.Slider(0, 1, step=0.05, value=0.75, visible=False)
        api_filter_radius = gr.Slider(0, 7, step=1, value=3, visible=False)
        api_uvr5_agg = gr.Slider(0, 20, step=1, value=settings.uvr5_agg, visible=False)
        api_uvr5_tta = gr.Checkbox(value=settings.uvr5_tta, visible=False)
        api_uvr5_postprocess = gr.Checkbox(value=settings.uvr5_postprocess, visible=False)
        api_uvr5_window_size = gr.Dropdown(
            choices=[256, 512, 1024], value=settings.uvr5_window_size, visible=False
        )
        api_uvr5_high_end_process = gr.Dropdown(
            choices=["mirroring", "none"], value=settings.uvr5_high_end_process, visible=False
        )
        api_msst_batch_size = gr.Number(value=2, visible=False)
        api_msst_num_overlap = gr.Number(value=4, visible=False)
        api_msst_normalize = gr.Checkbox(value=True, visible=False)
        api_vocal_postprocess = gr.Checkbox(value=False, visible=False)
        api_shift_accompaniment = gr.Checkbox(value=True, visible=False)
        api_output = gr.Audio(type="filepath", visible=False, label="API 音频输出")
        api_cache_flag = gr.Textbox(visible=False)

        # ---------------- 事件绑定 ----------------
        def handle_refresh():
            names = pipeline.refresh_models()
            log.info(f"模型列表已刷新：{len(names)} 个")
            return _dropdown_update(choices=names, value=(names[0] if names else None))

        def handle_switch(model_name: str) -> str:
            if not model_name:
                return "❌ 请先选择一个音色模型"
            try:
                model = pipeline.registry.get(model_name)
                text = f"✅ 已选中：{model.name}\nPTH: {model.pth_path}"
                text += (
                    f"\nINDEX: {model.index_path.name}（相似度 {model.index_score:.2f}）"
                    if model.index_path
                    else "\nINDEX: 未匹配到检索文件（音色更接近底模）"
                )
                log.info(text.replace("\n", " | "))
                return text
            except Exception as exc:
                log.error(f"切换音色失败: {exc}")
                return f"❌ {exc}"

        def handle_status() -> dict:
            payload = pipeline.status()
            payload["cache"] = cache_store.cache_info(settings)
            return payload

        def handle_ui_convert(
            song, key, vvol, ivol, model, reverb, delay, f0, index_rate, filter_radius,
            agg, tta, post, window, high_end, vocal_fx, shift_inst,
            progress: gr.Progress = gr.Progress(),
        ):
            if not song:
                raise gr.Error("请填写歌曲来源")
            if not model:
                raise gr.Error("请先选择音色模型")
            params = _to_params(
                song, model, key, vvol, ivol, reverb, delay, f0, index_rate, filter_radius,
                agg, tta, post, window, high_end, vocal_fx, shift_inst, settings,
            )
            return run_pipeline(params, progress)

        refresh_btn.click(handle_refresh, inputs=[], outputs=[model_dropdown], api_name=False)
        switch_btn.click(handle_switch, inputs=[model_dropdown], outputs=[model_status], api_name=False)
        clear_btn.click(
            lambda scope: cache_store.clear_cache(scope, settings),
            inputs=[cache_scope],
            outputs=[cache_json],
            api_name=False,
        )
        run_btn.click(
            handle_ui_convert,
            inputs=[
                song_input, key_shift_in, vocal_vol_in, inst_vol_in, model_dropdown,
                reverb_in, delay_in, f0_in, index_rate_in, filter_radius_in,
                uvr5_agg_in, uvr5_tta_in, uvr5_post_in, uvr5_window_in, uvr5_high_end_in,
                vocal_fx_in, shift_inst_in,
            ],
            outputs=[audio_out, result_info],
            api_name=False,
        )

        # ===== 对外 API（插件调用） =====
        gr.Button("API Show Model", visible=False).click(
            fn=lambda: pipeline.models(),
            inputs=[],
            outputs=[gr.JSON(visible=False)],
            api_name="show_model",
        )

        if is_svc:
            gr.Button("API Convert", visible=False).click(
                handle_convert_svc,
                inputs=[
                    song_input, key_shift_in, vocal_vol_in, inst_vol_in, api_model_name,
                    reverb_in, delay_in, api_uvr5_agg, api_uvr5_tta, api_uvr5_postprocess,
                    api_uvr5_window_size, api_uvr5_high_end_process, api_msst_batch_size,
                    api_msst_num_overlap, api_msst_normalize, api_vocal_postprocess,
                    api_shift_accompaniment, api_f0_method,
                ],
                outputs=[api_output, api_cache_flag],
                api_name="convert",
            )
        else:
            gr.Button("API Convert", visible=False).click(
                handle_convert_rvc,
                inputs=[
                    song_input, key_shift_in, vocal_vol_in, inst_vol_in, api_model_name,
                    reverb_in, delay_in, api_f0_method, api_index_rate, api_filter_radius,
                    api_uvr5_agg, api_uvr5_tta, api_uvr5_postprocess, api_uvr5_window_size,
                    api_uvr5_high_end_process, api_msst_batch_size, api_msst_num_overlap,
                    api_msst_normalize, api_vocal_postprocess, api_shift_accompaniment,
                ],
                outputs=[api_output, api_cache_flag],
                api_name="convert",
            )

        app.load(
            lambda: cache_store.cache_info(settings),
            inputs=[],
            outputs=[cache_json],
            api_name="cache_info",
        )
        gr.Button("API Clear Cache", visible=False).click(
            lambda scope: cache_store.clear_cache(scope, settings),
            inputs=[cache_scope],
            outputs=[gr.JSON(visible=False)],
            api_name="clear_cache",
        )
        gr.Button("API Status", visible=False).click(
            handle_status,
            inputs=[],
            outputs=[gr.JSON(visible=False)],
            api_name="status",
        )

    return app


# ----------------------------------------------------------------------
def _port_in_use(host: str, port: int) -> bool:
    """检查端口是否已被占用（仅用于给出友好提示）。"""
    import socket

    probe_host = host if host not in {"0.0.0.0", "::"} else "127.0.0.1"
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((probe_host, int(port))) == 0


def _port_owner_hint(port: int) -> str:
    """尽量查出占用端口的进程，返回可直接执行的排查提示。"""
    try:
        import subprocess

        output = subprocess.run(
            ["netstat", "-ano"], capture_output=True, text=True, timeout=10, errors="ignore"
        ).stdout
        for line in output.splitlines():
            if f":{port} " in line and "LISTENING" in line.upper():
                pid = line.split()[-1]
                return (
                    f"占用进程 PID={pid}\n"
                    f"  结束它：taskkill /PID {pid} /F\n"
                    f"  或改用其它端口：python app_{'svc' if port != 3333 else 'rvc'}.py --port {port + 1}"
                )
    except Exception:
        pass
    return f"  排查：netstat -ano | findstr :{port}，再 taskkill /PID <PID> /F"


def main(mode: str, argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=f"ApplioSVC-API ({mode})")
    parser.add_argument("--host", default=None, help="监听地址，默认读取 config.json")
    parser.add_argument("--port", type=int, default=None, help="监听端口")
    parser.add_argument("--share", action="store_true", help="开启 Gradio 公网分享")
    args = parser.parse_args(argv)

    settings, pipeline = _bootstrap(mode)
    app = build_ui(mode, settings, pipeline)

    host = args.host or settings.host
    port = args.port or (settings.svc_port if mode == "svc" else settings.rvc_port)
    share = bool(args.share or settings.share)

    _warn_environment()

    if not share and _port_in_use(host, port):
        log.error(f"端口 {port} 已被占用，无法启动（配置里 host={host}）")
        log.error(_port_owner_hint(port))
        log.error("提示：中间层只能有一个实例占着同一个端口；重复双击启动脚本也会出现这个错误。")
        return 2

    log.info(f"服务启动：http://{host}:{port} | API: /convert /show_model /cache_info /clear_cache")
    app.queue(
        max_size=int(settings.queue_size),
        api_open=True,
        default_concurrency_limit=1,
    )
    try:
        app.launch(
            server_name=host,
            server_port=port,
            share=share,
            show_error=settings.show_error,
            # 推理时工作目录会切到 Applio，必须显式允许项目内的成品/缓存目录
            allowed_paths=[str(TEMP_DIR), str(OUTPUT_DIR)],
            quiet=False,
        )
    except OSError as exc:
        log.error(f"启动失败：{exc}")
        log.error(_port_owner_hint(port))
        return 2
    return 0


def _warn_environment() -> None:
    """打印关键依赖来源，便于排查「版本对不上」类问题。"""
    try:
        import gradio

        version = getattr(gradio, "__version__", "?")
        log.info(f"Gradio {version} <- {gradio.__file__}")
        major = int(str(version).split(".")[0])
        if major != 5:
            log.warning(
                f"当前 Gradio 主版本为 {major}，本项目按 Gradio 5 的接口调优；"
                "如出现 API 不兼容请固定为 gradio 5.x"
            )
    except Exception as exc:  # pragma: no cover
        log.warning(f"读取 Gradio 版本失败: {exc}")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(os.environ.get("APPLIOSVC_MODE", "rvc")))
