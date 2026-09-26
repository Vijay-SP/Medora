"""Shared speech API contracts, using local synthetic PCM and an injected ASR engine."""
import io
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
import wave

_ROOT = Path(tempfile.mkdtemp(prefix='medpark-speech-tests-'))
for _key in ('DATA_DIR','UPLOADS_DIR','EXPORTS_DIR','FIXTURES_DIR','VOICEPRINTS_DIR','MODELS_DIR'):
    os.environ[_key] = str(_ROOT / _key.lower())
os.environ.update(SMTP_HOST='127.0.0.1', SMTP_PORT='9', ALLOW_SIMULATED_DELIVERY='false')
from fastapi.testclient import TestClient
from app.models.transcript import TranscriptSegment


def pcm():
    output = io.BytesIO()
    with wave.open(output, 'wb') as wav:
        wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(16000)
        wav.writeframes(b'\x00\x00' * 1600)
    return output.getvalue()


class Engine:
    device = 'metal'
    model_name = 'test-model'
    def __init__(self):
        self.calls = 0
        self.active = 0
        self.maximum = 0
        self.gate = threading.Event(); self.gate.set()
    def health(self):
        return {'ready': True, 'device': self.device, 'model': self.model_name}
    def transcribe(self, path, initial_prompt=None, language=None):
        self.calls += 1; self.active += 1; self.maximum = max(self.maximum, self.active)
        self.gate.wait(3)
        self.active -= 1
        return [TranscriptSegment(start=0, end=.1, raw_text='Hello team.', language='en')]
    def cancel(self):
        self.gate.set()


class SpeechTests(unittest.TestCase):
    def setUp(self):
        from app.speech_server import create_app, SpeechSettings
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.engine = Engine()
        self.config = SpeechSettings(data_dir=Path(self.temp.name), max_pending_jobs=2, max_upload_bytes=100_000)
        self.app = create_app(self.config, self.engine)
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
    def post(self, key='test-key'):
        return self.client.post('/v1/asr/jobs', files={'file':('audio.wav', pcm(), 'audio/wav')}, headers={'Idempotency-Key':key})
    def wait(self, job_id):
        for _ in range(80):
            result = self.client.get('/v1/asr/jobs/'+job_id).json()
            if result['status'] in ('completed','failed'): return result
            time.sleep(.03)
        self.fail('worker did not finish')
    def test_job_result_idempotency_and_delete(self):
        first=self.post(); self.assertEqual(first.status_code,202,first.text)
        job_id=first.json()['job_id']
        second=self.post(); self.assertEqual(second.json()['job_id'],job_id)
        result=self.wait(job_id)
        self.assertEqual(result['status'],'completed',result)
        self.assertEqual(result['result']['segments'][0]['raw_text'],'Hello team.')
        self.assertEqual(result['result']['device'],'metal')
        self.assertEqual(self.engine.calls,1)
        self.assertEqual(self.client.delete('/v1/asr/jobs/'+job_id).status_code,204)
        self.assertEqual(self.client.get('/v1/asr/jobs/'+job_id).status_code,404)
    def test_queue_is_bounded_and_worker_serial(self):
        self.engine.gate.clear()
        a=self.post('a'); b=self.post('b'); c=self.post('c')
        self.assertEqual([a.status_code,b.status_code,c.status_code],[202,202,429])
        self.assertEqual(self.client.delete('/v1/asr/jobs/'+a.json()['job_id']).status_code,409)
        self.engine.gate.set()
        self.wait(a.json()['job_id']); self.wait(b.json()['job_id'])
        self.assertEqual(self.engine.maximum,1)
    def test_rejects_bad_audio_options_and_oversized_body(self):
        bad=self.client.post('/v1/asr/jobs',files={'file':('a.wav',b'bad','audio/wav')})
        self.assertEqual(bad.status_code,422,bad.text)
        bad=self.client.post('/v1/asr/jobs',files={'file':('a.wav',pcm(),'audio/wav')},data={'language':'xx'})
        self.assertEqual(bad.status_code,422)
        bad=self.client.post('/v1/asr/jobs',content=b'x'*100_001,headers={'Content-Type':'application/octet-stream'})
        self.assertEqual(bad.status_code,413)
        self.assertEqual(list((Path(self.temp.name)/'uploads').glob('*')),[])
    def test_optional_auth_and_unavailable_runtime(self):
        from app.speech_server import create_app, SpeechSettings
        with TestClient(create_app(SpeechSettings(data_dir=Path(self.temp.name)/'secure',api_key='test-secret'),self.engine)) as client:
            self.assertEqual(client.get('/ready').status_code,401)
            self.assertEqual(client.get('/ready',headers={'Authorization':'Bearer test-secret'}).status_code,200)
            self.assertEqual(client.get('/health').status_code,200)
        self.engine.health=lambda: {'ready':False,'device':'metal','model':'test-model'}
        self.assertFalse(self.client.get('/ready').json()['ready'])
        self.assertEqual(self.post().status_code,503)

if __name__=='__main__': unittest.main()
