import base64
import importlib.util
import io
from pathlib import Path

import pytest

pytest.importorskip('PIL')
from PIL import Image

spec = importlib.util.spec_from_file_location('local_vision_adapter', Path(__file__).parents[1] / 'scripts' / 'serve_local_transformers.py')
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)


def test_decode_inline_images_preserves_text_and_pixels():
    buffer = io.BytesIO()
    Image.new('RGB', (10, 10), color='red').save(buffer, format='PNG')
    url = 'data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode()
    messages, images = adapter.decode_messages([{'role': 'user', 'content': [
        {'type': 'text', 'text': '描述画面'}, {'type': 'image_url', 'image_url': {'url': url}}]}])
    assert messages[0]['content'] == [{'type': 'text', 'text': '描述画面'}, {'type': 'image'}]
    assert len(images) == 1 and images[0].getpixel((0, 0)) == (255, 0, 0)


def test_remote_images_are_not_fetched():
    with pytest.raises(ValueError, match='不下载外部图片'):
        adapter.decode_messages([{'role': 'user', 'content': [{'type': 'image_url', 'image_url': {'url': 'https://example.com/private.png'}}]}])
