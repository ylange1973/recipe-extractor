import sys
import logging
from flask import Flask, request, jsonify
import subprocess
import os
import re
import tempfile

logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = Flask(__name__)

@app.route('/', methods=['GET'])
def root():
    return jsonify({'status': 'ok'})

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok'})

@app.route('/extract', methods=['POST'])
def extract():
    data = request.json
    url = data.get('url')
    if not url:
        return jsonify({'error': 'url required'}), 400

    logger.info(f"extract called with url: {url}")

    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            result = subprocess.run([
                'yt-dlp',
                '--write-auto-sub', '--sub-lang', 'en',
                '--skip-download', '--write-description',
                '-o', os.path.join(tmpdir, 'media'),
                url
            ], capture_output=True, text=True, timeout=60)

            logger.info(f"yt-dlp returncode: {result.returncode}")
            logger.info(f"yt-dlp stdout: {result.stdout[-500:] if result.stdout else 'none'}")
            logger.info(f"yt-dlp stderr: {result.stderr[-500:] if result.stderr else 'none'}")

            # Check for description file
            desc_file = os.path.join(tmpdir, 'media.description')
            if os.path.exists(desc_file):
                with open(desc_file, 'r', encoding='utf-8') as f:
                    text = f.read().strip()
                logger.info(f"description found, length: {len(text)}")
                if text and len(text) > 100:
                    return jsonify({'text': text, 'method': 'description'})

            # Check for subtitle file
            files = os.listdir(tmpdir)
            logger.info(f"files in tmpdir: {files}")
            for f in files:
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
                    logger.info(f"subtitle text length: {len(text)}")
                    if text and len(text) > 100:
                        return jsonify({'text': text, 'method': 'transcript'})

        except Exception as e:
            logger.error(f"extract error: {str(e)}")

        logger.info("returning null result")
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

    logger.info(f"transcribe called with url: {url}")

    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            result = subprocess.run([
                'yt-dlp',
                '--no-playlist',
                '-f', 'worstaudio',
                '-o', os.path.join(tmpdir, 'audio.%(ext)s'),
                url
            ], capture_output=True, text=True, timeout=120)

            logger.info(f"yt-dlp transcribe returncode: {result.returncode}")
            logger.info(f"yt-dlp transcribe stderr: {result.stderr[-500:] if result.stderr else 'none'}")

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
            logger.error(f"transcribe error: {str(e)}")
            return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000)) 
    app.run(host='0.0.0.0', port=port)
