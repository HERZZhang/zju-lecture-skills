#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
zju-lecture skill 的 agent 友好 CLI。

设计原则：
- stdout 只输出 JSON 结果（机器可读），进度/日志走 stderr；
- 所有子命令失败时也输出 {"ok": false, "error": "..."} 并以非零码退出；
- 登录态 / API key 走 secure_store（Windows DPAPI / macOS Keychain），不落明文。

常用：
    python zju_zy.py status
    python zju_zy.py login
    python zju_zy.py fetch  "<回放URL>" [--ppt] [--vision] [--out DIR]
    python zju_zy.py summarize "<回放URL>" [--no-ppt] [--out DIR]
    python zju_zy.py ppt  "<回放URL>" [--vision] [--out DIR]
    python zju_zy.py extract <课件文件>
    python zju_zy.py providers
"""
import argparse
import json
import os
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import pipeline          # noqa: E402
import secure_store      # noqa: E402
import zju_login         # noqa: E402
import pdf_render        # noqa: E402

DEFAULT_OUT_NAME = "zju-lecture-output"


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def emit(obj):
    json.dump(obj, sys.stdout, ensure_ascii=False, indent=2)
    print()
    sys.stdout.flush()


def ensure_secret_dir():
    """DSH 沙箱通常只允许写工作区：默认密钥目录（~ 下）不可写时，
    回退到当前目录的 .zju-secret-store（仍是 DPAPI 加密落盘）。"""
    d = secure_store._FALLBACK_DIR
    try:
        os.makedirs(d, exist_ok=True)
        probe = os.path.join(d, ".probe")
        with open(probe, "w", encoding="utf-8") as f:
            f.write("1")
        os.unlink(probe)
        return d
    except Exception:
        alt = os.path.join(os.getcwd(), ".zju-secret-store")
        os.makedirs(alt, exist_ok=True)
        secure_store._FALLBACK_DIR = alt
        log(f"提示：默认密钥目录不可写，已回退到 {alt}（DPAPI 加密）")
        return alt


def out_root_of(args):
    return os.path.abspath(args.out or os.path.join(os.getcwd(), DEFAULT_OUT_NAME))


def result_dir_of(out_root, sub_id):
    return os.path.join(out_root, f"{datetime.now():%Y%m%d}_sub{sub_id}")


def load_key(args):
    """优先级：--key > 钥匙串里已存的 api_key。"""
    key = (getattr(args, "key", None) or "").strip()
    if key:
        return key
    return secure_store.load_api_key()


def provider_from_args(args):
    """把 CLI 参数组装成 pipeline.resolve_api 认的 provider dict。"""
    pid = args.provider or "deepseek"
    preset = pipeline.PROVIDERS.get(pid, {})
    p = {"id": pid}
    if args.base_url:
        p["base"] = args.base_url
    if args.chat_model:
        p["chat"] = args.chat_model
    if args.vision_model:
        p["vision"] = args.vision_model
    # 若用户没覆盖，preset 里的值会在 resolve_api 里补全
    return p if len(p) > 1 else None


def ensure_cookie(anonymous=False):
    if anonymous:
        return None
    cookie = secure_store.load_cookie()
    if cookie:
        return cookie
    log("尚未登录（钥匙串里没有 Cookie）。先运行：python zju_zy.py login")
    return None


# ------------------------------------------------------------------ 子命令

def cmd_status(args):
    cookie = secure_store.load_cookie()
    info = zju_login.validate_cookie(cookie) if cookie else None
    key = secure_store.load_api_key()
    out = {
        "ok": True,
        "platform": sys.platform,
        "python": sys.executable,
        "storage_backend": secure_store.backend_name(),
        "cookie": {
            "present": bool(cookie),
            "valid": bool(info),
            "user": info or None,
        },
        "api_key": {"present": bool(key)},
        "api_config": {"present": bool(secure_store.load_api_config())},
        "ffmpeg": pipeline.ffmpeg_path(),
        "providers": {k: v["label"] for k, v in pipeline.PROVIDERS.items()},
    }
    emit(out)


def cmd_login(args):
    if args.timeout and args.timeout > 0:
        zju_login.LOGIN_TIMEOUT = args.timeout
    cookie, who = zju_login.ensure_login(force=args.force, progress=log)
    emit({"ok": True, "user": who, "cookie_length": len(cookie)})


def cmd_logout(args):
    zju_login.logout()
    emit({"ok": True, "message": "已清除本地登录态"})


def cmd_set_key(args):
    key = (args.key or "").strip()
    if not key:
        import getpass
        key = getpass.getpass("API key: ").strip()
    if not key:
        raise pipeline.PipelineError("API key 为空，未保存")
    secure_store.save_api_key(key)
    emit({"ok": True, "saved": True,
          "backend": secure_store.backend_name()})


def cmd_clear_key(args):
    secure_store.clear_api_key()
    emit({"ok": True, "message": "已清除 API key"})


def cmd_fetch(args):
    out_root = out_root_of(args)
    info = pipeline.parse_url(args.url)
    sub_id, tenant = info["sub_id"], info["tenant_code"]
    cookie = ensure_cookie(args.anonymous)

    segs = pipeline.fetch_transcript(sub_id, tenant, cookie)
    pipeline.check_transcript_quality(segs)
    per_seg, per_min, _minutes = pipeline.build_transcript_texts(segs)

    rdir = result_dir_of(out_root, sub_id)
    raw_dir = os.path.join(rdir, "raw")
    os.makedirs(raw_dir, exist_ok=True)
    with open(os.path.join(raw_dir, "transcript.txt"), "w", encoding="utf-8") as f:
        f.write(per_seg)
    with open(os.path.join(raw_dir, "transcript_by_minute.txt"), "w", encoding="utf-8") as f:
        f.write(per_min)

    out = {
        "ok": True, "course_id": info["course_id"], "sub_id": sub_id,
        "result_dir": rdir, "transcript_path": os.path.join(raw_dir, "transcript.txt"),
        "minute_path": os.path.join(raw_dir, "transcript_by_minute.txt"),
        "segments": len(segs), "duration": pipeline.fmt_ts(segs[-1][0]),
        "ppt_dir": None, "slide_count": 0,
    }

    if args.vision:
        args.ppt = True
    if args.ppt:
        if not cookie:
            log("未登录，跳过 PPT（PPT 接口需要登录态）")
        else:
            try:
                slides = pipeline.fetch_ppt_slides(
                    info["course_id"], sub_id, cookie, log)
            except pipeline.PipelineError as e:
                slides = []
                log(f"PPT 抓取失败：{e}")
            if slides:
                ppt_dir = os.path.join(rdir, "ppt")
                manifest = pipeline.download_slides(slides, ppt_dir, log)
                ok = sum(1 for m in manifest if m["status"] == "ok")
                out.update({"ppt_dir": ppt_dir, "slide_count": len(manifest),
                            "slide_ok": ok})
                platform_notes = [m for m in manifest if m.get("note")]
                if platform_notes:
                    with open(os.path.join(ppt_dir, "ppt_text.txt"), "w",
                              encoding="utf-8") as f:
                        for m in platform_notes:
                            ts = pipeline.fmt_ts(m["t_sec"]) if isinstance(
                                m.get("t_sec"), int) and m["t_sec"] >= 0 else "--:--:--"
                            f.write(f"[{ts}] 第{m['index']}页 {m['note']}\n")
                    out["ppt_ocr"] = "platform"
                elif args.vision:
                    key = load_key(args)
                    if not key:
                        log("--vision 需要 API key（--key 或钥匙串），已跳过转写")
                    else:
                        base, _chat, vis = pipeline.resolve_api(args.provider or "deepseek")
                        text = pipeline.transcribe_slides(
                            manifest, ppt_dir, key, log,
                            base_url=args.base_url or base,
                            vision_model=args.vision_model or vis)
                        out["ppt_ocr"] = "vision"
                        out["ppt_text_chars"] = len(text)
            else:
                log("该课程没有 PPT 幻灯片（或已不可用）")

    emit(out)


def cmd_ppt(args):
    out_root = out_root_of(args)
    info = pipeline.parse_url(args.url)
    sub_id = info["sub_id"]
    cookie = ensure_cookie(args.anonymous)
    if not cookie:
        raise pipeline.PipelineError("PPT 接口需要登录态，请先 login")

    slides = pipeline.fetch_ppt_slides(info["course_id"], sub_id, cookie, log)
    if not slides:
        emit({"ok": True, "slide_count": 0, "message": "没有可用的 PPT 幻灯片"})
        return

    rdir = result_dir_of(out_root, sub_id)
    ppt_dir = os.path.join(rdir, "ppt")
    manifest = pipeline.download_slides(slides, ppt_dir, log)
    ok = sum(1 for m in manifest if m["status"] == "ok")
    out = {"ok": True, "ppt_dir": ppt_dir, "slide_count": len(manifest),
           "slide_ok": ok, "manifest_md": os.path.join(ppt_dir, "manifest.md")}

    platform_notes = [m for m in manifest if m.get("note")]
    if platform_notes:
        with open(os.path.join(ppt_dir, "ppt_text.txt"), "w",
                  encoding="utf-8") as f:
            for m in platform_notes:
                ts = pipeline.fmt_ts(m["t_sec"]) if isinstance(
                    m.get("t_sec"), int) and m["t_sec"] >= 0 else "--:--:--"
                f.write(f"[{ts}] 第{m['index']}页 {m['note']}\n")
        out["ppt_ocr"] = "platform"
    if args.vision and not platform_notes:
        key = load_key(args)
        if not key:
            raise pipeline.PipelineError("--vision 需要 API key（--key 或钥匙串）")
        base, _chat, vis = pipeline.resolve_api(args.provider or "deepseek")
        text = pipeline.transcribe_slides(
            manifest, ppt_dir, key, log, base_url=args.base_url or base,
            vision_model=args.vision_model or vis)
        out["ppt_ocr"] = "vision"
        out["ppt_text_chars"] = len(text)
    emit(out)


def cmd_summarize(args):
    out_root = out_root_of(args)
    key = load_key(args)
    if not key:
        raise pipeline.PipelineError(
            "缺少 API key：请用 --key 传入，或先把它存进钥匙串（见 SKILL.md）")
    courseware = None
    if args.courseware:
        courseware = pipeline.extract_courseware(args.courseware)
        log(f"已读取课件：{args.courseware}（{len(courseware)} 字）")
    res = pipeline.run_pipeline(
        args.url, api_key=key,
        out_root=out_root, progress=log, mode="summarize",
        courseware_text=courseware,
        extra_requirements=args.extra,
        provider=provider_from_args(args),
        fetch_ppt=not args.no_ppt)
    out = {"ok": True, **res}
    if not args.no_pdf:
        try:
            out["pdf_path"] = pdf_render.render_pdf(
                res["summary_path"], progress=log)
        except Exception as e:      # noqa: BLE001  渲染失败不影响 Markdown 产出
            log(f"PDF 生成失败（讲义 Markdown 已保存）：{e}")
    emit(out)


def cmd_extract(args):
    text = pipeline.extract_courseware(args.file)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)
        emit({"ok": True, "chars": len(text), "output": os.path.abspath(args.out)})
    else:
        emit({"ok": True, "chars": len(text), "text": text})


def cmd_pdf(args):
    pdf_path = pdf_render.render_pdf(args.md, pdf_path=args.out, progress=log)
    emit({"ok": True, "pdf_path": pdf_path})


def cmd_providers(args):
    emit({"ok": True, "providers": pipeline.PROVIDERS})


# ------------------------------------------------------------------ 参数

def build_parser():
    p = argparse.ArgumentParser(
        description="智云课堂采编 CLI（zju-lecture skill）")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("status", help="自检：登录态 / key / ffmpeg")
    s.set_defaults(func=cmd_status)

    s = sub.add_parser("login", help="登录智云课堂（Playwright 弹窗）")
    s.add_argument("--force", action="store_true", help="忽略已有登录态，强制重登")
    s.add_argument("--timeout", type=int, default=0,
                   help="登录窗口最长等待秒数（默认 300）")
    s.set_defaults(func=cmd_login)

    s = sub.add_parser("logout", help="清除本地登录态")
    s.set_defaults(func=cmd_logout)

    s = sub.add_parser("set-key", help="把 API key 存入系统钥匙串（不落明文）")
    s.add_argument("--key", help="API key（不给则从终端隐藏输入）")
    s.set_defaults(func=cmd_set_key)

    s = sub.add_parser("clear-key", help="清除已存的 API key")
    s.set_defaults(func=cmd_clear_key)

    def add_ai_args(sp):
        sp.add_argument("--key", help="API key（不给则读钥匙串）")
        sp.add_argument("--provider", default="deepseek",
                        choices=list(pipeline.PROVIDERS.keys()),
                        help="API 提供商（默认 deepseek）")
        sp.add_argument("--base-url", help="覆盖提供商端点")
        sp.add_argument("--chat-model", help="覆盖文本模型名")
        sp.add_argument("--vision-model", help="覆盖视觉模型名")

    for name, help_ in (("fetch", "抓字幕（+可选 PPT）"),
                        ("ppt", "抓 PPT 幻灯片（+可选视觉转写）")):
        s = sub.add_parser(name, help=help_)
        s.add_argument("url", help="智云课堂回放 URL")
        s.add_argument("--out", help="输出根目录（默认 ./zju-lecture-output）")
        s.add_argument("--anonymous", action="store_true", help="不带登录态尝试")
        if name == "fetch":
            s.add_argument("--ppt", action="store_true", help="同时下载 PPT 图片")
        s.add_argument("--vision", action="store_true",
                       help="下载后做视觉转写（需要 API key）")
        add_ai_args(s)
        s.set_defaults(func=cmd_fetch if name == "fetch" else cmd_ppt)

    s = sub.add_parser("summarize", help="抓字幕 + AI 生成课程知识总结")
    s.add_argument("url", help="智云课堂回放 URL")
    s.add_argument("--out", help="输出根目录（默认 ./zju-lecture-output）")
    s.add_argument("--no-ppt", action="store_true", help="跳过 PPT 抓取（省钱模式）")
    s.add_argument("--no-pdf", action="store_true", help="不自动生成 PDF")
    s.add_argument("--courseware", help="附带课件文件（pptx/docx/pdf/txt/md）")
    s.add_argument("--extra", help="附加给总结模型的额外要求")
    add_ai_args(s)
    s.set_defaults(func=cmd_summarize)

    s = sub.add_parser("extract", help="从课件文件提取纯文字")
    s.add_argument("file", help="pptx / docx / pdf / txt / md")
    s.add_argument("--out", help="写入文件而不是打印到 stdout")
    s.set_defaults(func=cmd_extract)

    s = sub.add_parser("pdf", help="把已有讲义 Markdown 渲染成 PDF")
    s.add_argument("md", help="知识总结.md 路径")
    s.add_argument("--out", help="输出 PDF 路径（默认同目录同名 .pdf）")
    s.set_defaults(func=cmd_pdf)

    s = sub.add_parser("providers", help="列出内置 API 提供商预设")
    s.set_defaults(func=cmd_providers)

    return p


def main():
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass
    args = build_parser().parse_args()
    ensure_secret_dir()
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
