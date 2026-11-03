"""Standalone smoke test: in-process Applio (RVC) inference with a local .pth model."""

import os
import sys
import time

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APPLIO_DIR = os.environ.get("APPLIO_DIR") or r"D:\dsh项目\ApplioV3.6.5"

VOCAL = os.path.join(PROJECT_DIR, "temp", "_selftest_sep", "vocal_reference.wav_10.wav")
MODEL = os.path.join(APPLIO_DIR, "logs", "luotianyi_song", "FeiyuVoice-RVC-v1.pth")
INDEX = os.path.join(APPLIO_DIR, "logs", "luotianyi_song", "FeiyuVoice-RVC-v1.index")
OUT = os.path.join(PROJECT_DIR, "temp", "_selftest_infer", "out.wav")


def main() -> int:
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    # Applio resolves rvc/configs/*.json and rvc/models/* relative to the CWD.
    os.chdir(APPLIO_DIR)
    sys.path.insert(0, APPLIO_DIR)

    import torch
    from rvc.infer.infer import VoiceConverter

    print(f"cwd={os.getcwd()} cuda={torch.cuda.is_available()}")

    vc = VoiceConverter()
    t0 = time.time()
    vc.convert_audio(
        audio_input_path=VOCAL,
        audio_output_path=OUT,
        model_path=MODEL,
        index_path=INDEX,
        pitch=0,
        f0_method="rmvpe",
        index_rate=0.75,
        volume_envelope=1.0,
        protect=0.33,
        split_audio=False,
        embedder_model="contentvec",
        embedder_model_custom=None,
        clean_audio=False,
        export_format="WAV",
    )
    print(f"inference took {time.time() - t0:.1f}s")
    import soundfile as sf

    info = sf.info(OUT)
    print(f"output: {OUT} sr={info.samplerate} dur={info.duration:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
