import os
import logging
from flask import Flask, request, jsonify, render_template
import requests
from werkzeug.utils import secure_filename
from flask_cors import CORS
from io import BytesIO
import concurrent.futures

# --- Thiết lập Flask ---
app = Flask(__name__, template_folder="templates")

# Giới hạn kích thước file upload (5MB)
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024  # 5 MB

# Bật CORS
CORS(app, resources={r"/upload": {"origins": "*"}})

# Logging cơ bản
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# --- Cấu hình Deepgram ---
DEEPGRAM_API_KEY = "95e26fe061960fecb8fc532883f92af0641b89d0"
DEEPGRAM_ENDPOINT = "https://api.deepgram.com/v1/listen"
ALLOWED_EXTENSIONS = {'wav', 'mp3', 'm4a', 'flac'}

# Tạo thread pool cho các tác vụ I/O bound
executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)

# Tạo session tái sử dụng với connection pooling
session = requests.Session()
session.headers.update({
    'Authorization': f'Token {DEEPGRAM_API_KEY}',
    'Accept-Encoding': 'gzip'
})
session.mount('https://', requests.adapters.HTTPAdapter(
    pool_connections=10,
    pool_maxsize=10,
    max_retries=3
))

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

async def transcribe_with_deepgram(audio_bytes: bytes, ext: str) -> str:
    """Gửi audio lên Deepgram và trả về transcript (async)"""
    content_type = f'audio/{ext}'
    
    try:
        with BytesIO(audio_bytes) as audio_stream:
            response = session.post(
                DEEPGRAM_ENDPOINT,
                data=audio_stream,
                headers={'Content-Type': content_type},
                params={
                    'language': 'vi',
                    'model': 'nova-2',
                    'punctuate': 'true',
                    'utterances': 'true'
                },
                timeout=10
            )
            response.raise_for_status()
            
            data = response.json()
            return data['results']['channels'][0]['alternatives'][0]['transcript']
            
    except requests.exceptions.RequestException as e:
        logging.error(f"Deepgram request failed: {str(e)}")
        raise RuntimeError(f"Lỗi kết nối Deepgram: {str(e)}")
    except Exception as e:
        logging.error(f"Deepgram processing error: {str(e)}")
        raise RuntimeError("Lỗi xử lý kết quả từ Deepgram")

@app.route('/')
def index():
    return render_template('test.html')

@app.route('/upload', methods=['POST'])
def upload_audio():
    # Kiểm tra file
    if 'file' not in request.files:
        return jsonify({'error': 'Không có file được tải lên'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'Không có file được chọn'}), 400
    
    if not allowed_file(file.filename):
        return jsonify({'error': 'Định dạng file không được hỗ trợ'}), 400
    
    # Đọc file vào memory
    try:
        audio_bytes = file.read()
        if len(audio_bytes) == 0:
            return jsonify({'error': 'File rỗng'}), 400
            
        ext = file.filename.rsplit('.', 1)[1].lower()
    except Exception as e:
        logging.error(f"File read error: {str(e)}")
        return jsonify({'error': 'Lỗi đọc file'}), 500
    
    # Xử lý bất đồng bộ
    try:
        # Sử dụng thread pool để không block main thread
        future = executor.submit(transcribe_with_deepgram, audio_bytes, ext)
        transcript = future.result(timeout=15)  # Timeout 15s
    except concurrent.futures.TimeoutError:
        logging.error("Deepgram request timeout")
        return jsonify({'error': 'Timeout khi xử lý audio'}), 504
    except Exception as e:
        logging.error(f"Transcription error: {str(e)}")
        return jsonify({'error': str(e)}), 500
    
    return jsonify({'transcript': transcript}), 200

if __name__ == '__main__':
    # Production nên dùng Gunicorn với worker threads
    app.run(debug=False, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
