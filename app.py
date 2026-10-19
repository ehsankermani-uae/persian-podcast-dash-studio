import asyncio
import os
import re
import tempfile
import time
import zipfile
from pathlib import Path

import gradio as gr
import fitz
import edge_tts
from deep_translator import GoogleTranslator


VOICES = {
    "خانم جوان (پیش‌فرض)": "fa-IR-DilaraNeural",
    "آقا": "fa-IR-FaridNeural",
}


def read_document(path):
    suffix = Path(path).suffix.lower()

    if suffix == ".pdf":
        with fitz.open(path) as pdf:
            pages = [
                page.get_text("text", sort=True).strip()
                for page in pdf
            ]

        if not any(pages):
            raise gr.Error(
                "متن قابل استخراج نیست؛ PDF اسکن‌شده به OCR نیاز دارد."
            )

        return pages

    if suffix == ".txt":
        for encoding in ("utf-8-sig", "utf-16", "cp1252"):
            try:
                return [
                    Path(path).read_text(encoding=encoding)
                ]
            except UnicodeError:
                pass

        raise gr.Error(
            "رمزگذاری فایل متنی پشتیبانی نمی‌شود."
        )

    raise gr.Error(
        "فقط PDF و TXT پشتیبانی می‌شوند."
    )


def split_text(text, limit=2800):
    text = re.sub(r"[ \t]+", " ", text).strip()

    if not text:
        return []

    pieces = re.split(
        r"(?<=\n)|(?<=[.!?])\s+",
        text
    )

    chunks = []
    current = ""

    for piece in pieces:
        piece = piece.strip()

        if not piece:
            continue

        while len(piece) > limit:
            if current:
                chunks.append(current)
                current = ""

            cut = piece.rfind(" ", 0, limit)

            if cut < limit // 2:
                cut = limit

            chunks.append(
                piece[:cut].strip()
            )

            piece = piece[cut:].strip()

        if not piece:
            continue

        if len(current) + len(piece) + 1 > limit:
            if current:
                chunks.append(current)

            current = piece

        else:
            current = (
                current + "\n" + piece
            ).strip()

    if current:
        chunks.append(current)

    return chunks


def translate_piece(text):
    error = None

    for attempt in range(4):
        try:
            translated = GoogleTranslator(
                source="en",
                target="fa"
            ).translate(text)

            if translated and translated.strip():
                return translated.strip()

            raise RuntimeError(
                "پاسخ ترجمه خالی بود"
            )

        except Exception as exc:
            error = exc
            time.sleep(
                min(2 ** attempt, 8)
            )

    raise RuntimeError(
        f"سرویس ترجمه پاسخ نداد: {error}"
    )


def write_text(path, text):
    Path(path).write_text(
        text,
        encoding="utf-8-sig"
    )


def translate_document(
    file,
    omit_first_line,
    progress=gr.Progress()
):
    if not file:
        raise gr.Error(
            "ابتدا فایل PDF یا TXT را انتخاب کنید."
        )

    pages = read_document(file)

    if omit_first_line:
        for i, page in enumerate(pages):
            if page.strip():
                pages[i] = page.partition("\n")[2]
                break

    chunks = [
        (page_no, chunk)
        for page_no, page in enumerate(pages, 1)
        for chunk in split_text(page)
    ]

    if not chunks:
        raise gr.Error(
            "متنی برای ترجمه
