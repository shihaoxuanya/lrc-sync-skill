#!/usr/bin/env python3
"""Generate a 12-second synthetic WAV with three beeps. Contains no song audio."""
import argparse
import math
import struct
import wave
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('-o', '--output', type=Path, default=Path('work/demo.wav'))
args = parser.parse_args()
if args.output.exists():
    parser.error(f'输出已存在，未覆盖：{args.output}')
args.output.parent.mkdir(parents=True, exist_ok=True)
rate = 16000
frames = bytearray()
for i in range(12 * rate):
    t = i / rate
    amplitude = 0.0
    for j, onset in enumerate((1.0, 4.0, 7.0)):
        elapsed = t - onset
        if 0 <= elapsed < 0.6:
            envelope = min(1.0, elapsed / 0.01, (0.6 - elapsed) / 0.04)
            amplitude = 0.20 * envelope * math.sin(2 * math.pi * (440 + j * 110) * elapsed)
    frames.extend(struct.pack('<h', round(amplitude * 32767)))
with wave.open(str(args.output), 'wb') as audio:
    audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(rate); audio.writeframes(frames)
print(args.output)
