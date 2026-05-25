from flask import Flask, request, jsonify
import subprocess
import os
import re
import tempfile

app = Flask(__name__)

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok'})

@app.route('/extract', methods=['POST'])
def extract():
    data = request.json
    url = data.get('url')
    if not url:
        return jsonify({'error': 'url required'}), 400

    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            result = subprocess.run([
                'yt-dlp',
                '--write-auto-sub', '--sub-lang', 'en',
                '--skip-download', '--write-description',
                '-o', os.path.join(tmpdir, 'media'),
                url
            ], capture_output=True, text=True, timeout=60)

            # Check for description file
            desc_file = os.path.join(tmpdir, 'media.description')
            if os.path.exists(desc_file):
                with open(desc_file, 'r', encoding='utf-8') as f:
                    text = f.read().strip()
                if text and len(text) > 100:
                    return jsonify({'text': text, 'method': 'description'})

            # Check for subtitle file
            for f in os.listdir(tmpdir):
                if f.endswith('.vtt') or f.endswith('.srt'):
                    with open(os.path.join(tmpdir, f), 'r', encoding='utf-8') as sf:
                        raw = sf.read()
                    lines = raw.split('\n')
                    seen = set()
                    clean = []
                    for line in lines:
                        line = re.sub(r'<[^>]+>', '', line).strip()
                        if line and not line.startswith('WEBVTT') and '-->' not in line and line not in seen:
                            seen.add(line)
                            clean.append(line)
                    text = ' '.join(clean)
                    if text and len(text) > 100:
                        return jsonify({'text': text, 'method': 'transcript'})

        except Exception as e:
            pass

        return jsonify({'text': None, 'method': None})


@app.route('/transcribe', methods=['POST'])
def transcribe():
    data = request.json
    url = data.get('url')
    if not url:
        return jsonify({'error': 'url required'}), 400

    openai_key = os.environ.get('OPENAI_API_KEY')
    if not openai_key:
        return jsonify({'error': 'OPENAI_API_KEY not set'}), 500

    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            subprocess.run([
                'yt-dlp',
                '--no-playlist',
                '-f', 'worstaudio',
                '-o', os.path.join(tmpdir, 'audio.%(ext)s'),
                url
            ], capture_output=True, text=True, timeout=120)

            audio_file = None
            for f in os.listdir(tmpdir):
                audio_file = os.path.join(tmpdir, f)
                break

            if not audio_file:
                return jsonify({'error': 'Could not download audio'}), 500

            from openai import OpenAI
            client = OpenAI(api_key=openai_key)
            with open(audio_file, 'rb') as f:
                transcript = client.audio.transcriptions.create(
                    model='whisper-1',
                    file=f,
                    response_format='text'
                )
            return jsonify({'text': transcript, 'method': 'whisper'})

        except Exception as e:
            return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
