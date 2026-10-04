"""Turn record.mjs output (timestamped shop/panel screenshots + events.json + the agent's voice WAV saved by the
backend) into the four screen-recording shots make_film.py expects in ../recordings/.
Layout: Amazon tab (1280x800) left, Second Look panel (440x800) right, 30 fps, agent voice muxed on its real timeline."""
import glob
import json
import os
import subprocess
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
REC = os.path.join(HERE, "..", "recordings")
FR = os.path.join(HERE, "frames")


def concat_list(kind: str, path: str, start: float):
    files = sorted(glob.glob(f"{FR}/*_{kind}.jpg"), key=lambda f: float(os.path.basename(f).split("_")[1]))
    ts = [float(os.path.basename(f).split("_")[1]) for f in files]
    # pad the head so both streams start at the same clock time
    files, ts = [files[0]] + files, [start] + ts
    with open(path, "w") as fh:
        for i, f in enumerate(files):
            dur = (ts[i + 1] - ts[i]) if i + 1 < len(files) else 0.1
            fh.write(f"file '{f}'\nduration {dur:.3f}\n")
        fh.write(f"file '{files[-1]}'\n")


def run(*a):
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *a], check=True)


def main():
    ev = {e["name"]: e for e in json.load(open(os.path.join(HERE, "events.json")))}
    starts = [float(os.path.basename(f).split("_")[1]) for f in glob.glob(f"{FR}/*.jpg")]
    first = min(starts)
    concat_list("shop", "/tmp/sl_shop.txt", first)
    concat_list("panel", "/tmp/sl_panel.txt", first)
    full = os.path.join(HERE, "full.mp4")
    # frame timeline starts at `first` seconds after t0
    run("-f", "concat", "-safe", "0", "-i", "/tmp/sl_shop.txt", "-f", "concat", "-safe", "0", "-i", "/tmp/sl_panel.txt",
        "-filter_complex", # Sized for the film's 1536x864 device frame: the panel runs full height (it's the product),
        # the Amazon page is cropped to the product column beside it.
        "[0:v]fps=30,crop=982:800:0:0,scale=1060:864:flags=lanczos,setsar=1[a];"
        "[1:v]fps=30,scale=476:864:flags=lanczos,setsar=1[b];"
        "[a][b]hstack=2,format=yuv420p[v]",
        "-map", "[v]", "-c:v", "libx264", "-crf", "17", "-preset", "fast", "/tmp/sl_video.mp4")

    # agent voice: WAV starts at its file-name wall time; recording t0 wall = any event's wall - t
    wavs = sorted(glob.glob(os.path.join(REC, "raw", "agent_*.wav")))
    t0_wall = ev["ask"]["wall"] - ev["ask"]["t"]
    if wavs:
        w = wavs[-1]
        offset = float(os.path.basename(w)[6:-4]) - t0_wall - first
        delay_ms = max(0, int(offset * 1000))
        run("-i", "/tmp/sl_video.mp4", "-i", w, "-filter_complex",
            f"[1:a]adelay={delay_ms}|{delay_ms},aresample=48000,apad[a]", "-map", "0:v", "-map", "[a]",
            "-shortest", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", full)
    else:
        os.replace("/tmp/sl_video.mp4", full)

    def t(name, d=0.0):
        return max(0.0, ev[name]["t"] - first + d)

    def cut(out, a, b):
        run("-ss", f"{a:.2f}", "-to", f"{b:.2f}", "-i", full, "-c:v", "libx264", "-crf", "17", "-preset", "fast",
            "-c:a", "aac", "-b:a", "192k", os.path.join(REC, out))

    os.makedirs(REC, exist_ok=True)
    # shot lengths must cover the narration over them (s03 ~9 s, s04 ~18 s, s05 ~7 s, s06 ~8.5 s)
    cut("/tmp/sl_03.mp4", t("panel_ready", -8.0), t("ask", 1.0))
    run("-i", "/tmp/sl_03.mp4", "-vf", "tpad=start_duration=3.8:start_mode=clone", "-af", "adelay=3800|3800",
        "-c:v", "libx264", "-crf", "17", "-c:a", "aac", os.path.join(REC, "03_ask.mp4"))
    cut("04_cards.mp4", t("ask", 1.0), max(t("verdict", 5.0), t("ask", 20.0)))
    cut("05_verdict.mp4", max(t("verdict", 5.0), t("ask", 20.0)), t("verdict_spoken", 1.0))
    cut("06_watch.mp4", t("watch_typing", -0.5), t("end"))
    for f in sorted(glob.glob(os.path.join(REC, "0*.mp4"))):
        d = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", f],
                           capture_output=True, text=True).stdout.strip()
        print(os.path.basename(f), d)


if __name__ == "__main__":
    main()
