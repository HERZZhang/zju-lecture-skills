#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
lecture-transcribe —— 智云课堂「增强识别」手臂：视频 → 音频 → faster-whisper 重识别。

适用：平台字幕识别太差（口音重/术语错），或想拿到更干净的整课文字。
依赖：zju-lecture skill（复用其鉴权与 DPAPI 存储）+ faster-whisper + ffmpeg。

用法：
    python transcribe.py status
    python transcribe.py "<回放URL>" [--out DIR] [-o 输出.txt]
                        [--model large-v3] [--courseware 课件] [--keep-video]
                        [--download-ffmpeg]

stdout = JSON；进度走 stderr。
"""
import argparse
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
SKILLS_DIR = os.path.dirname(os.path.dirname(HERE))   # <.dsh>/skills
CORE_DIR = os.path.join(SKILLS_DIR, "zju-lecture", "scripts")

if not os.path.isdir(CORE_DIR):
    print(json.dumps({
        "ok": False,
        "error": f"缺少依赖 skill：{CORE_DIR} 不存在。先安装 zju-lecture skill。",
    }, ensure_ascii=False, indent=2))
    sys.exit(2)
if CORE_DIR not in sys.path:
    sys.path.insert(0, CORE_DIR)

import pipeline      # noqa: E402  （zju-lecture 的核心模块）
import secure_store  # noqa: E402
import zju_zy        # noqa: E402  （复用其密钥目录回退逻辑）

BASE = pipeline.BASE
INTERACTIVE_BASE = pipeline.INTERACTIVE_BASE
UA = pipeline.UA
SSL_CTX = pipeline.SSL_CTX
fmt_ts = pipeline.fmt_ts


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def emit(obj):
    json.dump(obj, sys.stdout, ensure_ascii=False, indent=2)
    print()
    sys.stdout.flush()


# ------------------------------------------------------------------ 视频

def _find_mp4(obj):
    """在 get-config 的 JSON 里递归找第一个 mp4 直链。"""
    if isinstance(obj, str):
        if obj.startswith("http") and ".mp4" in obj.split("?")[0]:
            return obj
        return None
    if isinstance(obj, dict):
        for v in obj.values():
            r = _find_mp4(v)
            if r:
                return r
    if isinstance(obj, list):
        for v in obj:
            r = _find_mp4(v)
            if r:
                return r
    return None


def fetch_video_url(course_id, sub_id, tenant_code, cookie, timeout=30):
    """带 Cookie 调 get-config，递归找出回放 mp4 直链。失败返回 None。"""
    if not cookie:
        return None
    url = (f"{BASE}/courseapi/v2/play-template/get-config"
           f"?course_id={course_id}&sub_id={sub_id}&tenant_code={tenant_code}")
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Cookie": cookie,
        "Referer": f"{BASE}/livingroom?sub_id={sub_id}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout,
                                    context=SSL_CTX) as r:
            data = json.loads(r.read().decode("utf-8"))
        return _find_mp4(data)
    except Exception:
        return None


def download_file(url, dest, timeout=3600):
    """流式下载大文件，进度每 ~4MB 报一次。返回字节数。"""
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as r:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        with open(dest, "wb") as f:
            while True:
                buf = r.read(1 << 18)
                if not buf:
                    break
                f.write(buf)
                done += len(buf)
                if total and done % (1 << 22) < (1 << 18):
                    log(f"   下载视频：{done // (1 << 20)} / "
                        f"{total // (1 << 20)} MB")
    return done


# ------------------------------------------------------------------ ffmpeg

def _ffmpeg_url():
    """eugeneware/ffmpeg-static 单文件静态构建（gzip 压缩）。"""
    import platform
    base = ("https://github.com/eugeneware/ffmpeg-static/releases/"
            "download/b6.0/")
    if os.name == "nt":
        return base + "ffmpeg-win32-x64.gz"
    arch = "arm64" if platform.machine() == "arm64" else "x64"
    return base + f"ffmpeg-darwin-{arch}.gz"


def download_ffmpeg():
    """下载静态 ffmpeg 到本脚本目录 bin/（约 20–25MB）。返回路径。"""
    import gzip
    url = _ffmpeg_url()
    bin_dir = os.path.join(HERE, "bin")
    os.makedirs(bin_dir, exist_ok=True)
    want = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    target = os.path.join(bin_dir, want)
    gzpath = target + ".gz"
    log(f"开始下载 ffmpeg：{url}")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=900, context=SSL_CTX) as r:
            total = int(r.headers.get("Content-Length") or 0)
            done = 0
            with open(gzpath, "wb") as f:
                while True:
                    buf = r.read(1 << 16)
                    if not buf:
                        break
                    f.write(buf)
                    done += len(buf)
                    if total:
                        log(f"   下载 ffmpeg：{done // (1 << 20)} / "
                            f"{total // (1 << 20)} MB")
        log("解压中…")
        with gzip.open(gzpath, "rb") as src, open(target, "wb") as dst:
            shutil.copyfileobj(src, dst)
    except Exception as e:
        raise pipeline.PipelineError(f"ffmpeg 下载失败：{e}")
    finally:
        try:
            os.unlink(gzpath)
        except OSError:
            pass
    if os.name != "nt":
        os.chmod(target, 0o755)
    log(f"ffmpeg 已就绪：{target}")
    return target


def ffmpeg_path(explicit=None):
    """优先显式路径 → skill bin/ → zju-lecture bin/ → 系统 PATH。"""
    if explicit:
        return explicit if os.path.isfile(explicit) else None
    candidates = [
        os.path.join(HERE, "bin", "ffmpeg.exe" if os.name == "nt" else "ffmpeg"),
        os.path.join(CORE_DIR, "bin", "ffmpeg.exe" if os.name == "nt" else "ffmpeg"),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return shutil.which("ffmpeg")


def extract_audio(ffmpeg, video_path, audio_path):
    log("用 ffmpeg 抽取音频（16kHz 单声道 mp3）…")
    r = subprocess.run(
        [ffmpeg, "-y", "-i", video_path, "-vn", "-ac", "1", "-ar", "16000",
         "-b:a", "32k", audio_path],
        capture_output=True, text=True, timeout=7200)
    if r.returncode != 0 or not os.path.isfile(audio_path):
        raise pipeline.PipelineError("ffmpeg 抽音频失败：" + (r.stderr or "")[-300:])


# ------------------------------------------------------------------ Whisper

WHISPER_PROMPT_BASE = "以下是浙江大学课堂的中文授课录音，请如实转写讲课内容。"


def build_whisper_prompt(courseware_text=None):
    prompt = WHISPER_PROMPT_BASE
    if courseware_text:
        head = re.sub(r"\s+", " ", courseware_text).strip()[:160]
        if head:
            prompt += "本课涉及：" + head
    return prompt


def whisper_transcribe(audio_path, model_size="large-v3", courseware_text=None):
    """faster-whisper 重识别，返回 [(BeginSec, Text), ...]。
    condition_on_previous_text=False 切断错误跨窗口传播（防一句话无限重复）。"""
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise pipeline.PipelineError(
            "增强识别需要 faster-whisper。请运行一次："
            "pip install faster-whisper（含模型自动下载，首次约 3GB）")
    prompt = build_whisper_prompt(courseware_text)
    log(f"加载 Whisper {model_size} 模型（首次自动下载）…")
    model = WhisperModel(model_size, device="auto", compute_type="auto")
    log(f"开始识别（较慢，耐心等）；提示词：{prompt[:60]}…")
    segments, _info = model.transcribe(
        audio_path, language="zh", initial_prompt=prompt,
        condition_on_previous_text=False,
        vad_filter=True, beam_size=5,
        compression_ratio_threshold=2.4,
        log_prob_threshold=-1.0,
        no_speech_threshold=0.6)
    segs, n = [], 0
    for s in segments:
        txt = (s.text or "").strip()
        if txt:
            segs.append((int(s.start), txt))
        n += 1
        if n % 50 == 0:
            log(f"   已识别 {n} 句，当前 {int(s.start) // 60} 分钟")
    if not segs:
        raise pipeline.PipelineError("Whisper 没有识别出任何内容")
    pipeline.check_transcript_quality(segs, log, "Whisper")
    return segs


# ------------------------------------------------------------------ CLI

def cmd_status(args):
    ff = ffmpeg_path(args.ffmpeg)
    try:
        import faster_whisper  # noqa: F401
        whisper_ok = True
        whisper_ver = getattr(faster_whisper, "__version__", "?")
    except ImportError:
        whisper_ok, whisper_ver = False, None
    cookie = secure_store.load_cookie()
    info = None
    if cookie:
        try:
            import importlib
            zju_login = importlib.import_module("zju_login")
            info = zju_login.validate_cookie(cookie)
        except Exception:
            info = None
    emit({
        "ok": True,
        "ffmpeg": ff,
        "faster_whisper": {"installed": whisper_ok, "version": whisper_ver},
        "cookie": {"present": bool(cookie), "valid": bool(info), "user": info},
        "core_skill_dir": CORE_DIR,
    })


def cmd_run(args):
    out_root = os.path.abspath(args.out or os.path.join(os.getcwd(),
                                                        "lecture-transcribe-output"))
    info = pipeline.parse_url(args.url)
    sub_id, tenant = info["sub_id"], info["tenant_code"]
    rdir = os.path.join(out_root, f"{datetime.now():%Y%m%d}_sub{sub_id}")
    raw = os.path.join(rdir, "raw")
    os.makedirs(raw, exist_ok=True)

    ff = ffmpeg_path(args.ffmpeg)
    if not ff:
        if args.download_ffmpeg:
            ff = download_ffmpeg()
        else:
            raise pipeline.PipelineError(
                "未找到 ffmpeg。加 --download-ffmpeg 自动下载（约 20MB），"
                "或 --ffmpeg 指定路径")

    cookie = (args.cookie or "").strip() or secure_store.load_cookie()
    if not cookie:
        raise pipeline.PipelineError("视频直链需要登录态：先运行 zju-lecture 的 login")

    video_url = args.video_url
    if not video_url:
        video_url = fetch_video_url(info["course_id"], sub_id, tenant, cookie)
    if not video_url:
        raise pipeline.PipelineError("拿不到视频直链（登录态可能过期，或该课不可下载）")

    video_path = os.path.join(raw, "video.mp4")
    if os.path.isfile(video_path) and os.path.getsize(video_path) > 0 and not args.force:
        log("检测到已下载视频，跳过重复下载")
    else:
        log("下载回放视频（可能 1–2GB，耐心等）…")
        size = download_file(video_url, video_path)
        log(f"   视频下载完成：{size // (1 << 20)} MB")

    audio_path = os.path.join(raw, "audio.mp3")
    if not os.path.isfile(audio_path) or args.force:
        extract_audio(ff, video_path, audio_path)

    courseware_text = None
    if args.courseware:
        courseware_text = pipeline.extract_courseware(args.courseware)
        log(f"已读取课件：{args.courseware}（{len(courseware_text)} 字）")

    segs = whisper_transcribe(audio_path, args.model, courseware_text)
    per_seg, per_min, _ = pipeline.build_transcript_texts(segs)

    out_path = args.output or os.path.join(rdir, "transcript_whisper.txt")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(per_seg)
    minute_path = os.path.join(rdir, "transcript_whisper_by_minute.txt")
    with open(minute_path, "w", encoding="utf-8") as f:
        f.write(per_min)

    if not args.keep_video:
        for p in (video_path, audio_path):
            try:
                os.unlink(p)
            except OSError:
                pass
        log("已清理视频/音频临时文件（--keep-video 可保留）")

    emit({"ok": True, "sub_id": sub_id, "result_dir": rdir,
          "transcript": out_path, "transcript_by_minute": minute_path,
          "segments": len(segs), "duration": fmt_ts(segs[-1][0]),
          "model": args.model})


def build_parser():
    p = argparse.ArgumentParser(description="智云课堂增强识别（faster-whisper）")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("status", help="检查 ffmpeg / faster-whisper / 登录态")
    s.add_argument("--ffmpeg")
    s.set_defaults(func=cmd_status)
    s = sub.add_parser("run", help="下载视频→抽音频→Whisper 重识别")
    s.add_argument("url", help="智云课堂回放 URL")
    s.add_argument("--out", help="输出根目录（默认 ./lecture-transcribe-output）")
    s.add_argument("-o", "--output", help="转写文本输出路径")
    s.add_argument("--model", default="large-v3", help="Whisper 模型（默认 large-v3）")
    s.add_argument("--courseware", help="课件文件（术语提示，可选）")
    s.add_argument("--video-url", help="直接给 mp4 直链（绕过自动获取）")
    s.add_argument("--cookie", help="直接给 Cookie 字符串（不推荐，会出现在命令历史）")
    s.add_argument("--ffmpeg", help="ffmpeg 可执行文件路径")
    s.add_argument("--download-ffmpeg", action="store_true",
                   help="ffmpeg 缺失时自动下载")
    s.add_argument("--keep-video", action="store_true", help="保留视频/音频文件")
    s.add_argument("--force", action="store_true", help="强制重新下载/重识别")
    s.set_defaults(func=cmd_run)
    return p


def main():
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass
    args = build_parser().parse_args()
    zju_zy.ensure_secret_dir()
    try:
        args.func(args)
    except pipeline.PipelineError as e:
        emit({"ok": False, "error": str(e)})
        sys.exit(2)
    except KeyboardInterrupt:
        emit({"ok": False, "error": "用户中断"})
        sys.exit(130)
    except Exception as e:  # noqa: BLE001
        emit({"ok": False, "error": f"{type(e).__name__}: {e}"})
        sys.exit(1)


if __name__ == "__main__":
    main()
