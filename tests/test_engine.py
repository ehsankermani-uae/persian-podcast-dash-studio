import json
import sqlite3
import fitz
import pytest
from book_engine import Book, Engine, extract, issues, split_exact, units

class Fake:
    glossary = {}
    def __init__(self): self.calls = 0
    def translate(self, source, draft=None):
        self.calls += 1
        return 'ترجمه کامل آزمایشی ' + source

def test_lossless_long():
    text = ('Chapter 1\nA sentence with 123 numbers.\n\nExample and explanation. ' * 2000) + 'X'*4000
    assert ''.join(split_exact(text)) == text
    assert max(map(len, split_exact(text))) <= 1800
    assert ''.join(s for _,_,s in units([text])) == text

def test_resume(tmp_path):
    b = Book(['First paragraph.\n\nSecond paragraph.'], {}, root=tmp_path)
    e = Fake()
    def stop(n, **kw):
        if n > 0: raise RuntimeError('interruption')
    with pytest.raises(RuntimeError): b.run(e, progress=stop)
    assert e.calls == 1
    b.close()
    b = Book(['First paragraph.\n\nSecond paragraph.'], {}, root=tmp_path)
    text, report = b.run(e)
    assert e.calls == 2
    assert not report['missing']
    b.run(e)
    assert e.calls == 2
    with sqlite3.connect(b.folder/'checkpoint.sqlite') as db:
        assert db.execute('select count(*) from chunks where target is null').fetchone()[0] == 0
    b.close()

def test_settings_isolation(tmp_path):
    a = Book(['Hello'], {'glossary': {}}, root=tmp_path)
    b = Book(['Hello'], {'glossary': {'hello':'سلام'}}, root=tmp_path)
    assert a.id != b.id
    a.close(); b.close()

def test_pdf(tmp_path):
    p = tmp_path/'sample.pdf'
    with fitz.open() as d:
        page = d.new_page()
        page.insert_text((72,72),'Chapter One\n\nAll examples must be translated. Number 42.')
        d.new_page().insert_text((72,72),'Second page. Nothing should be omitted.')
        d.save(p)
    pages, warnings = extract(p)
    assert len(pages) == 2
    assert '42' in pages[0]
    b = Book(pages, {}, root=tmp_path)
    text, report = b.run(Fake())
    assert not report['missing']
    assert 'Second page' in text
    assert 'All examples' in (b.folder/'bilingual.html').read_text()
    b.close()

def test_quality():
    assert 'empty' in issues('Some text','',{})
    assert 'number:42' in issues('Result 42', 'نتیجه', {})
    assert 'term:gradient' in issues('gradient descent', 'فرود', {'gradient':'گرادیان'})

def test_free_router_guard():
    with pytest.raises(ValueError): Engine('OpenRouter','paid-model','secret')

def test_failure_not_completed(tmp_path, monkeypatch):
    import book_engine
    monkeypatch.setattr(book_engine.time, 'sleep', lambda _: None)
    class Broken(Fake):
        def translate(self, *args): raise RuntimeError('offline')
    b = Book(['Hello'], {}, root=tmp_path)
    with pytest.raises(RuntimeError): b.run(Broken())
    _, report = b.export()
    assert len(report['missing']) == 1
    b.close()

def test_html_escaped(tmp_path):
    b = Book(['<script>alert(1)</script>'], {}, root=tmp_path)
    b.run(Fake())
    assert '<script>' not in (b.folder/'bilingual.html').read_text()
    b.close()

def test_review_pipeline(tmp_path):
    b = Book(['English content'], {}, root=tmp_path)
    e, r = Fake(), Fake()
    b.run(e, r)
    assert e.calls == r.calls == 1
    b.close()

def test_audio_resume_and_zip(tmp_path, monkeypatch):
    import asyncio
    import zipfile
    import app
    calls = []
    async def synth(text, voice, rate, output):
        calls.append(text)
        output.write_bytes(b'fake-audio-for-control-flow' * 20)
    monkeypatch.setattr(app, 'synthesize_chunk', synth)
    monkeypatch.setattr(app, 'ROOT', tmp_path)
    monkeypatch.setattr(app.shutil, 'which', lambda _: None)
    text = 'این یک آزمایش است. ' * 250
    first, archive = app.make_audio(text, 'خانم جوان (پیش‌فرض)', 0, lambda *a, **k: None)
    count = len(calls)
    assert count > 1
    app.make_audio(text, 'خانم جوان (پیش‌فرض)', 0, lambda *a, **k: None)
    assert len(calls) == count
    with zipfile.ZipFile(archive) as z:
        assert len(z.namelist()) == count
    # This verifies caching/packaging only, not real speech encoding.
