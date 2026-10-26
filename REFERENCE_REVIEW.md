# بررسی پروژه‌های مرجع

بررسی کد و مجوز در ۲۶ اکتبر ۲۰۲۶؛ کدی از این پروژه‌ها کپی نشده است. قابلیت‌ها مستقلاً در book_engine.py نوشته شده‌اند.

## hydropix/TranslateBooksWithLLMs

منبع: https://github.com/hydropix/TranslateBooksWithLLMs

مجوز AGPL-3.0. فایل‌های بررسی‌شده: `translate.py` و `src/persistence/checkpoint_manager.py` و `LICENSE`. معماری شامل CLI، adapter موتورهای متعدد، ماژول persistence و مدیریت checkpoint است. گزینه واژه‌نامه JSON/CSV و واژه‌نامه خودکار، ادامه کار و ذخیره وضعیت دارد. به دلیل دامنه بسیار بزرگ‌تر و تعهدات AGPL، ادغام مستقیم یا vendor کردن انجام نشد. پروژه فعلی هم مجوز اختصاصی در مخزن ندارد، بنابراین مجوز جدیدی به کل کار صاحب پروژه تحمیل نشده است.

## StephenGenusa/PDFTranslator

منبع: https://github.com/StephenGenusa/PDFTranslator

مجوز MIT. فایل‌های بررسی‌شده: `pyproject.toml`، `translate.py`، `scanner.py` و `orchestrator.py`. واحدهای خطی و ترجمه keyed، کنترل تطابق تعداد خطوط، cache دیسکی، rendering و حفظ صفحه‌آرایی دارد. وابستگی‌های اعلام‌شده Python >=3.14، PyMuPDF، LiteLLM، DiskCache، Pydantic و Typer است. این مجموعه برای برنامه ساده Python 3.11/3.12 سنگین و ناسازگار است. کد مستقلِ شناسه واحدها، صف بدون حذف و ذخیره SQLite جایگزین شد. حفظ layout تصویری این پروژه به محصول فعلی منتقل نشده است؛ HTML دوزبانه برای مقایسه استفاده می‌شود.

## مجوز وابستگی‌های مستقیم

Gradio Apache-2.0؛ deep-translator MIT؛ edge-tts LGPL-3.0؛ HTTPX BSD-3-Clause؛ PyMuPDF دارای AGPL-3.0 یا مجوز تجاری است. PyMuPDF از قبل در پروژه اصلی وجود داشت و ادامه استفاده از آن، نیاز بررسی تعهدات توزیع به‌خصوص در بسته اجرایی را از بین نمی‌برد. برای انتشار بسته اجرایی، متن مجوز وابستگی‌ها و سورس لازم را همراه خروجی فراهم کنید؛ workflow موجود صرفاً build فنی آزمایشی است، تأیید مجوز نهایی نیست.

شناسه نسخه‌های بررسی‌شده:
- مخزن اصلی: `4a9dd4d`
- TranslateBooksWithLLMs: `5c774a184893802d4f926c6f4550b208ddbe574d`
- PDFTranslator: `6aede02a386322b427543bc91c6ace2a08b9e655`
