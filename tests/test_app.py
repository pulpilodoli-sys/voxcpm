import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from docx import Document
from PySide6.QtWidgets import QApplication, QFileDialog
from dramascript.app import Window

# Keep the QApplication alive until module teardown, after all widgets.
APP = QApplication.instance() or QApplication([])


def test_gui_exports_and_review_tabs(tmp_path, monkeypatch):
    app = APP
    window = Window()
    window.project.setText(str(tmp_path))
    text = '第一场 内景 客厅 日\n小林放下信件。\n小林：明天见。'
    window.script.setPlainText(text)
    window.save_edit()
    assert (tmp_path / '剧本修订稿.txt').read_text(encoding='utf-8') == text
    path = tmp_path / '剧本.docx'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a: (str(path), ''))
    window.export_docx()
    assert '小林' in '\n'.join(p.text for p in Document(path).paragraphs)
    path = tmp_path / '剧本.pdf'
    window.export_pdf()
    assert path.read_bytes().startswith(b'%PDF')
    window.show_evidence({'chunks': [{'start': 120, 'end': 240, 'analysis': '人物出场', 'transcript': '你好'}]})
    assert window.seek_seconds.value() == 120
    window.mode.setCurrentText('本地')
    assert not window.key.isEnabled()
    assert window.tabs.count() == 3
    window.close()
    app.processEvents()
    import shiboken6
    shiboken6.delete(window)
    app.processEvents()
