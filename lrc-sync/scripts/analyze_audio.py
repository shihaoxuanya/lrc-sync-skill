#!/usr/bin/env python3
"""Inspect a local recording; plot waveform or excerpt spectrogram, never infer lyrics."""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path

from lrc_tool import probe_audio, local_file


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--start", type=float, default=0)
    parser.add_argument("--end", type=float)
    parser.add_argument("--spectrogram", action="store_true", help="仅为 <=90 秒的指定片段生成声谱，横轴为原音频秒数")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    try:
        import numpy as np
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from scipy import signal
        source = local_file(args.audio)
        info = probe_audio(source)
        start = args.start
        end = info["duration"] if args.end is None else args.end
        if not all(math.isfinite(x) for x in (start, end)) or not 0 <= start < end <= info["duration"]:
            raise ValueError("必须满足 0 <= start < end <= 音频时长。")
        if end - start > 1800:
            raise ValueError("单次分析最长 30 分钟，请用 --start / --end 分段。")
        if args.spectrogram and end - start > 90:
            raise ValueError("声谱片段最长 90 秒；建议先看全曲波形，再按 20–40 秒分段。")
        output = Path(args.out_dir)
        token = f"{start:.2f}_{end:.2f}"
        names = ["audio.json", f"waveform_{token}.png"]
        if args.spectrogram:
            names.append(f"spectrogram_{token}.png")
        if not args.force and any((output / name).exists() for name in names):
            raise ValueError("输出文件已存在；请另选目录，或明确使用 --force。")
        process = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(start), "-i", str(source),
                                  "-t", str(end - start), "-map", "0:a:0", "-vn", "-ac", "1",
                                  "-ar", "16000", "-f", "f32le", "pipe:1"],
                                 capture_output=True, check=False, timeout=180)
        if process.returncode:
            raise ValueError(process.stderr.decode(errors="replace")[:500])
        samples = np.frombuffer(process.stdout, dtype="<f4")
        if samples.size < 512:
            raise ValueError("片段太短或解码后无可用音频。")
        output.mkdir(parents=True, exist_ok=True)
        (output / "audio.json").write_text(json.dumps(info, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        # Min/max envelope retains transients that a sparse sample plot would miss.
        block = max(1, samples.size // 12000)
        usable = samples[:samples.size // block * block].reshape(-1, block)
        times = start + np.arange(usable.shape[0]) * block / 16000
        fig, ax = plt.subplots(figsize=(14, 3.2))
        ax.fill_between(times, usable.min(axis=1), usable.max(axis=1))
        ax.set(xlabel="Original audio time (seconds)", ylabel="Mixed amplitude", xlim=(start, end),
               title=f"Waveform | {start:.2f}–{end:.2f} s | not vocal detection")
        fig.tight_layout(); fig.savefig(output / names[1], dpi=150); plt.close(fig)
        if args.spectrogram:
            freq, time, power = signal.spectrogram(samples, fs=16000, nperseg=1024, noverlap=896, mode="psd")
            fig, ax = plt.subplots(figsize=(14, 4.6))
            mesh = ax.pcolormesh(time + start, freq, 10 * np.log10(np.maximum(power, 1e-12)), shading="auto")
            ax.set(xlabel="Original audio time (seconds)", ylabel="Frequency (Hz)", ylim=(80, 6500), xlim=(start, end),
                   title="Mixed-audio spectrogram | harmonics are evidence, not recognized words")
            fig.colorbar(mesh, ax=ax, label="Power spectral density (dB)")
            fig.tight_layout(); fig.savefig(output / names[2], dpi=150); plt.close(fig)
        print(json.dumps({"audio": info, "outputs": [str(output / name) for name in names],
                          "warning": "波形和声谱含有伴奏。峰值不等于起唱，不能仅凭图认定歌词或声称完成试听。"}, ensure_ascii=False, indent=2))
        return 0
    except ImportError as exc:
        print(f"依赖缺失：{exc}。安装 scripts/requirements.txt。", file=sys.stderr)
        return 2
    except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
