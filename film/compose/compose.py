"""Assemble the Second Look demo film from the real recordings, cards and ElevenLabs audio."""
import base64, glob, json, os, subprocess
import numpy as np

F = os.path.dirname(os.path.abspath(__file__))
FILM = os.path.dirname(F)
REC = os.path.join(FILM, 'rec')
AUD = os.path.join(FILM, 'audio')
OUT = os.path.join(F, 'out'); os.makedirs(OUT, exist_ok=True)
SR = 48000
FPS = 30


def run(cmd):
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def frames_video(pattern, kind, name, end_pad):
    files = sorted(glob.glob(pattern))
    if kind:
        files = [f for f in files if f.endswith(f'_{kind}.jpg')]
    ts = [float(os.path.basename(f).split('_')[1].replace('.jpg', '')) for f in files]
    lst = os.path.join(OUT, name + '.txt')
    with open(lst, 'w') as fh:
        fh.write(f"file '{files[0]}'\nduration {ts[0]:.3f}\n")   # hold first frame from t=0
        for i, f in enumerate(files):
            d = (ts[i + 1] - ts[i]) if i + 1 < len(files) else end_pad
            fh.write(f"file '{f}'\nduration {max(d, 0.001):.3f}\n")
        fh.write(f"file '{files[-1]}'\n")
    out = os.path.join(OUT, name + '.mp4')
    run(['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', lst, '-vf', f'fps={FPS},format=yuv420p', '-c:v', 'libx264', '-crf', '14', out])
    return out


ev = {e['name']: e['t'] for e in json.load(open(os.path.join(REC, 'live/events.json')))}
END = ev['end']
shop = frames_video(os.path.join(REC, 'live/frames/*.jpg'), 'shop', 'shop', END)
panel = frames_video(os.path.join(REC, 'live/frames/*.jpg'), 'panel', 'panel', 1)
inst1 = frames_video(os.path.join(REC, 'install/*.jpg'), None, 'inst1', 2)
inst2 = frames_video(os.path.join(REC, 'install2/*.jpg'), None, 'inst2', 1)

segs = []   # (file, duration)


def still(png, dur, name, zoom=True):
    out = os.path.join(OUT, name + '.mp4')
    vf = (f"scale=3840:-1,zoompan=z='1+0.035*on/({dur}*{FPS})':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={int(dur*FPS)}:s=1920x1080:fps={FPS}"
          if zoom else f"scale=1920:1080,fps={FPS}")
    run(['ffmpeg', '-y', '-loop', '1', '-t', str(dur), '-i', png, '-vf', vf + f",fade=in:st=0:d=0.5,fade=out:st={dur-0.4}:d=0.4,format=yuv420p",
         '-t', str(dur), '-c:v', 'libx264', '-crf', '14', out])
    segs.append((out, dur))


def windowed(png, src, a, b, speed, name, x, y, panel_src=None, fin=0.35, fout=0.0):
    dur = (b - a) / speed
    out = os.path.join(OUT, name + '.mp4')
    fc = f"[1:v]trim=start={a}:end={b},setpts=(PTS-STARTPTS)/{speed},scale=1280:800[s];[0:v][s]overlay={x}:{y}[v1];"
    if panel_src:
        fc += f"[2:v]trim=start={a}:end={b},setpts=(PTS-STARTPTS)/{speed},scale=440:800[p];[v1][p]overlay={x+1280}:{y}[v2];"
        last = 'v2'
    else:
        last = 'v1'
    fades = f"fade=in:st=0:d={fin}" if fin else "null"
    if fout:
        fades += f",fade=out:st={dur-fout}:d={fout}"
    fc += f"[{last}]{fades},fps={FPS},format=yuv420p[o]"
    ins = ['-loop', '1', '-t', str(dur), '-i', png, '-i', src] + (['-i', panel_src] if panel_src else [])
    run(['ffmpeg', '-y'] + ins + ['-filter_complex', fc, '-map', '[o]', '-t', f'{dur:.3f}', '-c:v', 'libx264', '-crf', '14', out])
    segs.append((out, dur))
    return dur


C = lambda n: os.path.join(F, n + '.png')
timeline = []   # (out_t, kind, payload)


def now():
    return sum(d for _, d in segs)


# --- intro ---
timeline.append((now() + 0.4, 'vo', 'vo_01')); still(C('problem'), 7.5, 's01')
timeline.append((now() + 0.3, 'vo', 'vo_02')); still(C('title'), 7.0, 's02')
timeline.append((now() + 0.2, 'vo', 'vo_03')); still(C('term'), 5.0, 's03', zoom=False)
windowed(C('inst_a'), inst1, 1.4, 9.1, 1.0, 's04', 320, 180)
windowed(C('inst_b'), inst2, 0.0, 5.4, 1.0, 's05', 320, 180, fout=0.4)

# --- live session (source seconds -> film) ---
live = [  # (png, a, b, speed, agent_audio, vo)
    ('live_a', 8.0, 20.0, 1.0, True, 'vo_04'),
    ('live_b', 20.0, 30.0, 1.0, True, None),
    ('live_b', 30.0, 43.0, 1.5, False, 'vo_05'),
    ('live_c', 43.0, 66.0, 1.0, True, None),
    ('live_d', 66.0, 84.0, 2.0, False, 'vo_07'),
    ('live_d', 84.0, min(92.0, END - 0.2), 1.0, True, None),
]
maps = []
for i, (png, a, b, sp, agent, vo) in enumerate(live):
    t = now()
    if vo:
        timeline.append((t + 0.2, 'vo', vo))
    if agent:
        maps.append((a, b, t))
    windowed(C(png), shop, a, b, sp, f'l{i}', 100, 180, panel_src=panel, fin=0.25 if i == 0 else 0,
             fout=0.4 if i == len(live) - 1 else 0)
# the spoken question: the fake mic plays 2 s of silence then q1 from the moment the mic opens
q_src = ev['mic_tap'] + 2.0
for a, b, t in maps:
    if a <= q_src < b:
        timeline.append((t + q_src - a, 'q1', None))

# --- end card ---
timeline.append((now() + 1.2, 'vo', 'vo_08'))
still(C('title'), 7.0, 's99')
TOTAL = now()
print('film length', round(TOTAL, 2))

# --- video concat ---
lst = os.path.join(OUT, 'segs.txt')
with open(lst, 'w') as fh:
    for f, _ in segs:
        fh.write(f"file '{f}'\n")
video = os.path.join(OUT, 'video.mp4')
run(['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', lst, '-c', 'copy', video])

# --- audio ---
def load(path):
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', path, '-f', 's16le', '-ac', '1', '-ar', str(SR), '-'], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.int16).astype(np.float32) / 32768


n = int((TOTAL + 0.5) * SR)
voice = np.zeros(n, np.float32)
agent = np.zeros(n, np.float32)


def place(buf, sig, t, gain=1.0):
    i = int(t * SR)
    if i >= len(buf):
        return
    sig = sig[: len(buf) - i]
    buf[i:i + len(sig)] += sig * gain


for t, kind, p in timeline:
    if kind == 'vo':
        place(voice, load(os.path.join(AUD, p + '.mp3')), t, 1.0)
    elif kind == 'q1':
        place(agent, load(os.path.join(REC, 'live/q1.mp3')), t, 0.9)

# agent speech: 24 kHz PCM chunks laid back to back from their arrival times, then mapped into the 1x segments
chunks = json.load(open(os.path.join(REC, 'live/audio.json')))
src_n = int((END + 30) * 24000)
src = np.zeros(src_n, np.float32)
cur = 0
for c in chunks:
    pcm = np.frombuffer(base64.b64decode(c['data']), np.int16).astype(np.float32) / 32768
    start = max(int(c['t'] * 24000), cur)
    seg = pcm[: src_n - start]
    src[start:start + len(seg)] += seg
    cur = start + len(seg)
x48 = np.interp(np.arange(int(src_n * 2)) / 2, np.arange(src_n), src).astype(np.float32)
for a, b, t in maps:
    piece = x48[int(a * SR):int(b * SR)].copy()
    ramp = int(0.08 * SR)
    piece[:ramp] *= np.linspace(0, 1, ramp); piece[-ramp:] *= np.linspace(1, 0, ramp)
    place(agent, piece, t, 1.0)

music = load(os.path.join(AUD, 'music.mp3'))[:n]
music = np.pad(music, (0, n - len(music)))
# duck the bed under any speech
speech = np.abs(voice) + np.abs(agent)
win = int(0.25 * SR)
env = np.convolve(speech, np.ones(win) / win, mode='same')
duck = np.clip(1 - env * 9, 0.32, 1.0)
duck = np.convolve(duck, np.ones(win) / win, mode='same')
fade = np.ones(n); f = int(2.5 * SR); fade[-f:] = np.linspace(1, 0, f); fade[:int(.6 * SR)] = np.linspace(0, 1, int(.6 * SR))
mix = voice * 1.0 + agent * 0.95 + music * 0.30 * duck * fade
mix = mix / max(1.0, np.max(np.abs(mix)) / 0.95)
wav = os.path.join(OUT, 'mix.wav')
import wave
with wave.open(wav, 'wb') as w:
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
    w.writeframes((mix * 32767).astype(np.int16).tobytes())

final = os.path.join(FILM, 'second-look-demo.mp4')
run(['ffmpeg', '-y', '-i', video, '-i', wav, '-map', '0:v', '-map', '1:a', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k',
     '-ac', '2', '-shortest', '-movflags', '+faststart', final])
print(final)
