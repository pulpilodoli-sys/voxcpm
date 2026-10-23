import json
from pathlib import Path
import subprocess

import pytest
from dramascript import engine
from tests.helpers import visual_reply


def test_incremental_video_pipeline(tmp_path, monkeypatch):
    video = tmp_path / 'silent.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=blue:s=160x120:d=1', '-y', str(video)], check=True)
    calls = []

    def fake_chat(config, messages):
        calls.append(messages)
        return visual_reply(messages)

    monkeypatch.setattr(engine, 'chat', fake_chat)
    config = dict(mode='本地', url='http://localhost:11434/v1', model='test', audio_model='small', key='secret-do-not-save')
    project = tmp_path / 'project'
    text, data = engine.process(video, project, config, lambda *a: None, lambda: False)
    assert len(calls) == 1
    assert data['chunks'][0]['transcript'] == '[无音轨]'
    assert list(project.glob('chunk-*/*.jpg'))
    assert '人物甲' in text
    assert 'secret-do-not-save' not in (project / 'project.json').read_text()
    assert any(c['type'] == 'image_url' for c in calls[0][1]['content'])
    engine.process(video, project, config, lambda *a: None, lambda: False)
    assert len(calls) == 1  # persisted chunks really bypass model requests
    config['model'] = 'different'
    with pytest.raises(RuntimeError, match='配置|设置'):
        engine.process(video, project, config, lambda *a: None, lambda: False)


def test_pause(tmp_path):
    video = tmp_path / 'video.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=d=1:s=160x120', '-y', str(video)], check=True)
    with pytest.raises(engine.Cancelled):
        engine.process(video, tmp_path / 'project', {'mode': '本地', 'url': 'http://localhost:11434/v1'}, lambda *a: None, lambda: True)


@pytest.mark.parametrize('config', [
    {'mode': '本地', 'url': 'https://remote.example/v1'},
    {'mode': '云端', 'url': 'http://remote.example/v1', 'key': 'x'},
    {'mode': '云端', 'url': 'https://user:secret@example.com/v1', 'key': 'x'},
    {'mode': '云端', 'url': 'https://example.com/v1?key=secret', 'key': 'x'},
])
def test_reject_unsafe_or_misleading_endpoints(config):
    with pytest.raises(RuntimeError):
        engine.validate_config(config)


def test_failed_later_chunk_resumes_with_previous_context(tmp_path, monkeypatch):
    video = tmp_path / 'long.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=r=1:d=121:s=160x120', '-y', str(video)], check=True)
    calls = []

    def fail_later(config, messages):
        calls.append(messages)
        if len(calls) == 2:
            raise RuntimeError('模拟第二片段服务中断')
        return visual_reply(messages, '小林携信离开。')

    config = {'mode': '本地', 'url': 'http://localhost:11434/v1', 'model': 'test'}
    monkeypatch.setattr(engine, 'chat', fail_later)
    project = tmp_path / 'project'
    with pytest.raises(RuntimeError, match='模拟'):
        engine.process(video, project, config, lambda *a: None, lambda: False)
    data = json.loads((project / 'project.json').read_text(encoding='utf-8'))
    assert len(data['chunks']) == 1
    assert not data['complete']
    resumed = []

    def recover(config, messages):
        resumed.append(messages)
        return visual_reply(messages, '下一场：小林保管信件。')

    monkeypatch.setattr(engine, 'chat', recover)
    text, data = engine.process(video, project, config, lambda *a: None, lambda: False)
    assert len(resumed) == 1
    assert '小林携信离开' in resumed[0][1]['content'][0]['text']
    assert len(data['chunks']) == 2 and data['complete']
    assert '小林携信离开' in text and '下一场' in text


def test_real_local_audio_decoder(tmp_path):
    """Regression: PyAV 19 removed the metadata_errors option used by Whisper."""
    import wave
    pytest.importorskip('faster_whisper')
    from faster_whisper.audio import decode_audio
    audio = tmp_path / 'silence.wav'
    with wave.open(str(audio), 'wb') as file:
        file.setnchannels(1)
        file.setsampwidth(2)
        file.setframerate(16000)
        file.writeframes(b'\x00\x00' * 1600)
    samples = decode_audio(str(audio))
    assert len(samples) == 1600


def test_scene_change_frames_have_ordered_times(tmp_path, monkeypatch):
    video = tmp_path / 'scene-change.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=blue:d=1:r=5:s=160x120',
                    '-f', 'lavfi', '-i', 'color=red:d=1:r=5:s=160x120',
                    '-filter_complex', '[0:v][1:v]concat=n=2:v=1:a=0[v]', '-map', '[v]', '-y', str(video)], check=True)
    monkeypatch.setattr(engine, 'chat', lambda config, messages: visual_reply(messages, '画面发生变化。'))
    _, data = engine.process(video, tmp_path / 'project', {'mode': '本地', 'url': 'http://localhost:11434/v1'}, lambda *a: None, lambda: False)
    samples = data['chunks'][0]['samples']
    exact = [s for s in samples if not s['approximate']]
    assert exact and exact[0]['time'] == pytest.approx(1.0, abs=0.21)
    assert [s['time'] for s in samples] == sorted(s['time'] for s in samples)


def test_non_chinese_model_response_is_not_accepted():
    with pytest.raises(RuntimeError, match='未包含中文'):
        engine.require_chinese('INT. ROOM - DAY\nA man enters.', '剧本正文')
    assert engine.require_chinese('内景 房间 日\n人物甲走进房间。', '剧本正文')


def test_truncated_model_response_is_not_accepted(monkeypatch):
    monkeypatch.setattr(engine, 'request', lambda *a: {'choices': [{'message': {'content': '未完成的剧本'}, 'finish_reason': 'length'}]})
    with pytest.raises(RuntimeError, match='不完整'):
        engine.chat({'url': 'http://localhost/v1', 'model': 'test'}, [])


def test_writer_gets_raw_speech_even_when_visual_model_claims_silence(tmp_path, monkeypatch):
    video = tmp_path / 'offscreen.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=blue:d=1:s=160x120',
                    '-f', 'lavfi', '-i', 'sine=d=1', '-t', '1', '-y', str(video)], check=True)
    monkeypatch.setattr(engine, 'transcribe', lambda *a: 'Do not open the door.')
    calls = []

    def model(config, messages):
        calls.append(messages)
        return '不要开门。' if len(calls) == 1 else visual_reply(messages, '画面无人可见。')

    monkeypatch.setattr(engine, 'chat', model)
    script, data = engine.process(video, tmp_path / 'project', {'mode': '云端', 'url': 'https://example.com/v1', 'key': 'test'}, lambda *a: None, lambda: False)
    assert calls[0][1]['content'] == 'Do not open the door.'
    assert 'Do not open the door.' not in str(calls[1])
    assert script.count('不要开门。') == 1
    assert '未识别声音' in script
    assert data['pipeline_version'] == engine.PIPELINE_VERSION


def test_identical_sample_frames_share_image_payload(tmp_path, monkeypatch):
    video = tmp_path / 'static.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=blue:d=22:r=1:s=160x120', '-y', str(video)], check=True)
    requests = []

    def model(config, messages):
        requests.append(messages)
        return visual_reply(messages, '蓝色画面，无可见人物。')

    monkeypatch.setattr(engine, 'chat', model)
    engine.process(video, tmp_path / 'project', {'mode': '本地', 'url': 'http://localhost:11434/v1'}, lambda *a: None, lambda: False)
    blocks = requests[0][1]['content']
    assert sum(b['type'] == 'image_url' for b in blocks) == 1
    assert any('采样间隙内容未知' in b.get('text', '') for b in blocks)


def test_non_project_files_are_never_overwritten(tmp_path):
    video = tmp_path / 'video.mp4'
    video.write_bytes(b'placeholder')
    project = tmp_path / 'existing'
    project.mkdir()
    valuable = project / 'user.txt'
    valuable.write_text('保留用户文件')
    with pytest.raises(RuntimeError, match='空文件夹'):
        engine.process(video, project, {'mode': '本地', 'url': 'http://localhost:11434/v1'}, lambda *a: None, lambda: False)
    assert valuable.read_text() == '保留用户文件'
    assert not (project / 'project.json').exists()


def test_retry_only_cleans_generated_frame_names(tmp_path, monkeypatch):
    video = tmp_path / 'video.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=d=1:s=160x120', '-y', str(video)], check=True)
    config = {'mode': '本地', 'url': 'http://localhost:11434/v1'}
    project = tmp_path / 'project'
    with pytest.raises(engine.Cancelled):
        engine.process(video, project, config, lambda *a: None, lambda: True)
    folder = project / 'chunk-00000'
    folder.mkdir()
    valuable = folder / 'user-photo.jpg'
    valuable.write_bytes(b'USER DATA')
    monkeypatch.setattr(engine, 'chat', lambda config, messages: visual_reply(messages))
    engine.process(video, project, config, lambda *a: None, lambda: False)
    assert valuable.read_bytes() == b'USER DATA'


def test_cli_and_gui_cannot_write_same_project_concurrently(tmp_path):
    from dramascript.storage import project_guard
    project = tmp_path / 'project'
    with project_guard(project):
        with pytest.raises(RuntimeError, match='占用'):
            engine.process(tmp_path / 'missing.mp4', project, {}, lambda *a: None, lambda: False)
    assert not (project / '.dramascript.lock').exists()
