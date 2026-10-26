
import asyncio
import re
import tempfile
import time
import zipfile
import hashlib
import json
import os
import shutil
import subprocess
from book_engine import Book, Engine, ROOT, extract
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
        if output.exists() and output.stat().st_size > 100:
            files.append(output)
            progress(index / len(chunks), desc=f"صدای ذخیره‌شده {index}")
            continue

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

    folder = ROOT / ("audio_" + hashlib.sha256((text + voice + str(rate)).encode()).hexdigest()[:24])
    folder.mkdir(parents=True, exist_ok=True)
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

    # FFmpeg decodes and re-encodes MP3; never concatenate MP3 bytes.
    groups = []
    if shutil.which("ffmpeg"):
        for offset in range(0, len(files), 20):
            group = files[offset:offset + 20]
            listing = folder / "concat.txt"
            listing.write_text("".join("file '" + f.name + "'\n" for f in group), encoding="utf-8")
            continuous = folder / f"section_{offset//20+1:04d}.mp3"
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
                            "-c:a", "libmp3lame", "-q:a", "3", str(continuous)], check=True)
            groups.append(continuous)
    archive = folder / "persian_podcast.zip"

    with zipfile.ZipFile(
        archive,
        "w",
        compression=zipfile.ZIP_DEFLATED
    ) as zf:
        for file in files + groups:
            zf.write(file, arcname=file.name)

    return str(files[0]), str(archive)



def full_book(file, omit, ocr, mode, provider, model, key, reviewer_provider,
              reviewer_model, reviewer_key, glossary_text, free_confirm, progress=gr.Progress()):
    if not file:
        raise gr.Error('ابتدا کتاب را انتخاب کنید.')
    try:
        glossary = json.loads(glossary_text or '{}')
        if not isinstance(glossary, dict) or not all(isinstance(k, str) and isinstance(v, str) and k and v for k,v in glossary.items()):
            raise ValueError('واژه‌نامه باید شیء JSON شامل عبارت انگلیسی و معادل فارسی باشد.')
        cloud = provider not in ('Google', 'Ollama') or (mode == 'دقیق' and reviewer_provider not in ('Google', 'Ollama'))
        if cloud and not free_confirm:
            raise ValueError('ابتدا تأیید کنید حساب API در طرح رایگان و بدون صورتحساب است.')
        engine = Engine(provider, model, key, glossary)
        reviewer = None
        if mode == 'دقیق':
            if reviewer_provider == 'Google':
                raise ValueError('برای بازبینی دقیق، موتور LLM انتخاب کنید؛ Google بازبین مستقل نیست.')
            if (provider, model) == (reviewer_provider, reviewer_model):
                raise ValueError('برای بررسی مستقل مدل یا موتور متفاوت انتخاب کنید.')
            reviewer = Engine(reviewer_provider, reviewer_model, reviewer_key, glossary)
        pages, warnings = extract(file, ocr)
        if omit:
            for i, page in enumerate(pages):
                if page.strip():
                    pages[i] = page.partition('\n')[2]
                    warnings.append('خط اول با انتخاب صریح کاربر حذف شد.')
                    break
        settings = dict(version=1, provider=provider, model=model, mode=mode,
                        reviewer=reviewer_provider if reviewer else '', reviewer_model=reviewer_model if reviewer else '',
                        glossary=glossary, ocr=ocr, omit=omit)
        book = Book(pages, settings, warnings)
        error = None
        try:
            text, report = book.run(engine, reviewer, progress)
        except Exception as exc:
            error = str(exc)
            text, report = book.export()
        finally:
            book.close()
        status = f"بخش‌ها: {report['total']} | ترجمه‌نشده: {len(report['missing'])} | نیازمند بررسی: {len(report['suspect'])}"
        if warnings:
            status += '\n' + '\n'.join(warnings)
        if error:
            status += '\nتوقف: ' + error + '\nبرای ادامه همان فایل و تنظیمات را انتخاب کنید و دوباره ترجمه کامل را بزنید.'
        status += '\nمسیر پیشرفت محلی: ' + str(book.folder)
        return text, [str(book.folder / n) for n in ('translation_fa.txt', 'bilingual.html', 'quality.json', 'book_backup.zip')], status
    except Exception as exc:
        raise gr.Error(str(exc)) from None


def audio_ui(text, voice, speed, progress=gr.Progress()):
    first, archive = make_audio(text, voice, speed, progress)
    folder = Path(archive).parent
    return first, archive, [str(p) for p in sorted(folder.glob('*.mp3'))]


with gr.Blocks(title='Persian Podcast Studio', css='.gradio-container {direction: rtl} textarea {text-align: start}') as demo:
    gr.Markdown('# 🎙️ استودیوی کتاب صوتی فارسی\nکتاب را انتخاب کنید ← ترجمه کامل ← ساخت کتاب صوتی')
    gr.Markdown('متن برای ترجمه آنلاین به سرویس انتخابی و برای صدا به Microsoft ارسال می‌شود. پیشرفت فقط روی دستگاه اجرا ذخیره می‌شود. تضمین کامل بودن معنایی با بازبینی انسانی است.')
    source_file = gr.File(label='۱. کتاب انگلیسی PDF یا TXT', file_types=['.pdf', '.txt'], type='filepath')
    with gr.Accordion('تنظیمات پیشرفته (اختیاری)', open=False):
        omit = gr.Checkbox(label='حذف عمدی خط اول (پیش‌فرض خاموش)', value=False)
        ocr = gr.Checkbox(label='OCR تمام صفحات PDF؛ نیازمند Tesseract انگلیسی', value=False)
        mode = gr.Radio(['سریع', 'دقیق'], value='سریع', label='روش ترجمه')
        provider = gr.Dropdown(['Google', 'Gemini', 'Groq', 'OpenRouter', 'Ollama'], value='Google', label='موتور اولیه')
        model = gr.Textbox(label='نام مدل (برای Google خالی؛ برای بقیه مطابق راهنما)')
        key = gr.Textbox(label='کلید اختیاری؛ ذخیره نمی‌شود', type='password')
        reviewer_provider = gr.Dropdown(['Gemini', 'Groq', 'OpenRouter', 'Ollama'], value='Ollama', label='موتور مستقل بازبینی و اصلاح در حالت دقیق')
        reviewer_model = gr.Textbox(label='مدل بازبین', value='qwen2.5:7b')
        reviewer_key = gr.Textbox(label='کلید بازبین', type='password')
        free_confirm = gr.Checkbox(label='حساب و مدل API انتخابی رایگان است و صورتحساب فعال نیست', value=False)
        glossary = gr.Textbox(label='واژه‌نامه JSON؛ Google فقط کنترل می‌کند، مدل‌ها در ترجمه استفاده می‌کنند', value='{}', placeholder='{"machine learning":"یادگیری ماشین"}')
    translate_button = gr.Button('۲. ترجمه کامل / ادامه ترجمه', variant='primary')
    status = gr.Textbox(label='پیشرفت و گزارش پوشش', lines=5)
    translation = gr.Textbox(label='۳. ترجمه فارسی (قابل ویرایش؛ ساخت صدا از همین متن)', lines=16)
    downloads = gr.Files(label='ترجمه TXT، مقایسه کامل HTML، گزارش و نسخه پشتیبان')
    gr.Markdown('فایل bilingual.html را دانلود و در مرورگر باز کنید تا تمام متن انگلیسی و فارسی را کنار هم ببینید. قبل از ساخت صدا، تعداد بخش‌های ترجمه‌نشده باید صفر باشد.')
    with gr.Row():
        voice_choice = gr.Dropdown(list(VOICES), value='خانم جوان (پیش‌فرض)', label='گوینده (سن صدا تضمین‌شده نیست)')
        speed = gr.Slider(-30, 30, value=0, step=5, label='سرعت درصد')
    audio_button = gr.Button('۴. ساخت کتاب صوتی MP3', variant='primary')
    audio_preview = gr.Audio(label='پخش فایل انتخابی', type='filepath')
    audio_zip = gr.File(label='۵. دانلود تمام قسمت‌ها ZIP')
    audio_files = gr.Files(label='فایل‌های MP3؛ برای پخش مسیر فایل را از منوی زیر انتخاب کنید')
    def choose_audio(files):
        return gr.Dropdown(choices=files or [], value=(files[0] if files else None))
    audio_select = gr.Dropdown(label='انتخاب قسمت برای پخش')
    translate_button.click(full_book, [source_file, omit, ocr, mode, provider, model, key, reviewer_provider, reviewer_model, reviewer_key, glossary, free_confirm], [translation, downloads, status], concurrency_limit=1)
    audio_button.click(audio_ui, [translation, voice_choice, speed], [audio_preview, audio_zip, audio_files], concurrency_limit=1).then(choose_audio, audio_files, audio_select)
    audio_select.change(lambda p: p, audio_select, audio_preview)

if __name__ == '__main__':
    demo.queue().launch(server_name='127.0.0.1', inbrowser=True, share=False)
