
import asyncio
import re
import tempfile
import time
import zipfile
from pathlib import Path

import edge_tts
import fitz
import gradio as gr
from deep_translator import GoogleTranslator


VOICES = {
    "خانم جوان (پیش‌فرض)": "fa-IR-DilaraNeural",
    "آقا": "fa-IR-FaridNeural",
}


def read_document(path):
    path = Path(path)
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        with fitz.open(path) as pdf:
            pages = [
                page.get_text("text", sort=True).strip()
                for page in pdf
            ]

        if not any(pages):
            raise gr.Error(
                "این PDF متن قابل استخراج ندارد. "
                "فایل اسکن‌شده به OCR نیاز دارد."
            )
        return pages

    if suffix == ".txt":
        for encoding in ("utf-8-sig", "utf-16", "cp1252"):
            try:
                return [path.read_text(encoding=encoding)]
            except UnicodeError:
                continue

        raise gr.Error("رمزگذاری فایل پشتیبانی نمی‌شود.")

    raise gr.Error("فقط فایل PDF و TXT قابل قبول است.")


def split_text(text, limit=2500):
    text = text.replace("\r\n", "\n").strip()
    if not text:
        return []

    chunks = []
    current = ""

    for paragraph in text.split("\n"):
        paragraph = paragraph.strip()
        if not paragraph:
            continue

        sentences = re.split(
            r"(?<=[.!?])\s+",
            paragraph
        )

        for sentence in sentences:
            while len(sentence) > limit:
                cut = sentence.rfind(" ", 0, limit)
                if cut < limit // 2:
                    cut = limit

                if current:
                    chunks.append(current)
                    current = ""

                chunks.append(sentence[:cut].strip())
                sentence = sentence[cut:].strip()

            if not sentence:
                continue

            if len(current) + len(sentence) + 1 > limit:
                if current:
                    chunks.append(current)
                current = sentence
            else:
                current = (
                    current + "\n" + sentence
                ).strip()

    if current:
        chunks.append(current)

    return chunks


def translate_piece(text):
    last_error = None

    for attempt in range(5):
        try:
            result = GoogleTranslator(
                source="en",
                target="fa"
            ).translate(text)

            if result and result.strip():
                return result.strip()

            raise RuntimeError("پاسخ ترجمه خالی بود.")

        except Exception as exc:
            last_error = exc
            time.sleep(min(2 ** attempt, 12))

    raise RuntimeError(
        f"ترجمه ناموفق بود: {last_error}"
    )


def save_text(path, text):
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
        raise gr.Error("ابتدا فایل PDF یا TXT انتخاب کنید.")

    pages = read_document(file)

    if omit_first_line:
        for index, page in enumerate(pages):
            if page.strip():
                pages[index] = page.partition("\n")[2]
                break

    chunks = [
        (page_number, chunk)
        for page_number, page in enumerate(pages, 1)
        for chunk in split_text(page)
    ]

    if not chunks:
        raise gr.Error("متنی برای ترجمه پیدا نشد.")

    output = []
    total = len(chunks)

    for index, (page_number, chunk) in enumerate(chunks):
        progress(
            (index + 1) / total,
            desc=f"ترجمه بخش {index + 1} از {total}"
        )

        try:
            translated = translate_piece(chunk)
        except Exception as exc:
            raise gr.Error(
                f"خطا در بخش {index + 1}: {exc}"
            )

        output.append(
            f"--- صفحه {page_number} ---\n{translated}"
        )

    full_translation = "\n\n".join(output)

    folder = Path(tempfile.mkdtemp(prefix="podcast_"))
    text_file = folder / "translation_fa.txt"
    save_text(text_file, full_translation)

    return full_translation, str(text_file)


def prepare_speech_text(text):
    text = re.sub(
        r"--- صفحه \d+ ---",
        "",
        text
    )
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


async def synthesize_chunk(text, voice, rate, output):
    communicator = edge_tts.Communicate(
        text=text,
        voice=voice,
        rate=f"{rate:+d}%"
    )
    await communicator.save(str(output))


async def create_audio_async(
    text,
    voice,
    rate,
    folder,
    progress
):
    chunks = split_text(text, limit=1800)

    if not chunks:
        raise gr.Error("متنی برای تبدیل به صدا وجود ندارد.")

    files = []

    for index, chunk in enumerate(chunks, 1):
        output = folder / f"part_{index:04d}.mp3"
        last_error = None

        for attempt in range(4):
            try:
                await synthesize_chunk(
                    chunk,
                    voice,
                    rate,
                    output
                )

                if output.exists() and output.stat().st_size > 0:
                    last_error = None
                    break

                raise RuntimeError("فایل صوتی خالی است.")

            except Exception as exc:
                last_error = exc
                output.unlink(missing_ok=True)
                await asyncio.sleep(min(2 ** attempt, 8))

        if last_error is not None:
            raise gr.Error(
                f"ساخت صدای بخش {index} ناموفق بود: "
                f"{last_error}"
            )

        files.append(output)

        progress(
            index / len(chunks),
            desc=f"ساخت صدا {index} از {len(chunks)}"
        )

    return files


def make_audio(
    text,
    voice_name,
    speed,
    progress=gr.Progress()
):
    if not text or not text.strip():
        raise gr.Error(
            "ابتدا متن فارسی را ترجمه یا وارد کنید."
        )

    voice = VOICES[voice_name]
    rate = int(speed)

    folder = Path(tempfile.mkdtemp(prefix="audio_"))
    clean_text = prepare_speech_text(text)

    files = asyncio.run(
        create_audio_async(
            clean_text,
            voice,
            rate,
            folder,
            progress
        )
    )

    archive = folder / "persian_podcast.zip"

    with zipfile.ZipFile(
        archive,
        "w",
        compression=zipfile.ZIP_DEFLATED
    ) as zf:
        for file in files:
            zf.write(file, arcname=file.name)

    return str(files[0]), str(archive)


with gr.Blocks(title="Persian Podcast Studio") as demo:
    gr.Markdown(
        "# 🎙️ Persian Podcast Studio\n"
        "ترجمه مقاله و کتاب انگلیسی به فارسی "
        "و ساخت پادکست MP3"
    )

    gr.Markdown(
        "ابتدا فایل را ترجمه کنید، سپس صدای دلخواه "
        "را انتخاب کنید و خروجی صوتی بگیرید."
    )

    source_file = gr.File(
        label="فایل مقاله یا کتاب انگلیسی",
        file_types=[".pdf", ".txt"],
        type="filepath"
    )

    omit_title = gr.Checkbox(
        label="حذف خط اول سند (مثلاً عنوان مقاله)",
        value=False
    )

    translate_button = gr.Button(
        "ترجمه کامل به فارسی",
        variant="primary"
    )

    translation = gr.Textbox(
        label="متن فارسی (قابل ویرایش)",
        lines=15,
        interactive=True,
        placeholder=(
            "ترجمه اینجا نمایش داده می‌شود. "
            "می‌توانید متن فارسی آماده را هم وارد کنید."
        )
    )

    text_download = gr.File(
        label="دانلود ترجمه فارسی TXT"
    )

    gr.Markdown("## 🎧 ساخت فایل صوتی فارسی")

    voice_choice = gr.Dropdown(
        choices=list(VOICES.keys()),
        value="خانم جوان (پیش‌فرض)",
        label="انتخاب گوینده"
    )

    speed = gr.Slider(
        minimum=-30,
        maximum=30,
        value=0,
        step=5,
        label="سرعت خواندن (درصد)"
    )

    audio_button = gr.Button(
        "ساخت پادکست MP3",
        variant="primary"
    )

    audio_preview = gr.Audio(
        label="شنیدن اولین قسمت",
        type="filepath"
    )

    audio_download = gr.File(
        label="دانلود تمام قسمت‌های MP3 در ZIP"
    )

    translate_button.click(
        fn=translate_document,
        inputs=[source_file, omit_title],
        outputs=[translation, text_download]
    )

    audio_button.click(
        fn=make_audio,
        inputs=[translation, voice_choice, speed],
        outputs=[audio_preview, audio_download]
    )

if __name__ == "__main__":
    demo.queue().launch()
