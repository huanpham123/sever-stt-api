import os
import logging
from flask import Flask, request, jsonify, render_template
import requests
from werkzeug.utils import secure_filename
from werkzeug.exceptions import RequestEntityTooLarge
from flask_cors import CORS

# --- Thiết lập Flask ---
app = Flask(__name__, template_folder="templates")

# Giới hạn kích thước file upload (5MB)
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024  # 5 MB

# Bật CORS cho route /upload
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


def transcribe_with_deepgram(audio_bytes: bytes, ext: str) -> str:
    """
    Gửi audio (bytes) lên Deepgram và trả về transcript.
    ext: phần mở rộng file (vd: 'wav', 'mp3', ...)
    """
    content_type = f'audio/{ext}'
    try:
        response = session.post(
            DEEPGRAM_ENDPOINT,
            data=audio_bytes,
            headers={'Content-Type': content_type},
            params={
                'language': 'vi',
                'model': 'nova-2',
                'punctuate': 'true',
                'utterances': 'true'
            },
            timeout=10  # Timeout 10s
        )
        response.raise_for_status()
        data = response.json()
        # Trả về transcript thuần túy
        return data['results']['channels'][0]['alternatives'][0]['transcript']
    except requests.exceptions.RequestException as e:
        logging.error(f"[Deepgram] Request failed: {e}")
        raise RuntimeError(f"Lỗi kết nối Deepgram: {e}")
    except Exception as e:
        logging.error(f"[Deepgram] Processing error: {e}")
        raise RuntimeError("Lỗi xử lý kết quả từ Deepgram")


# --- Routes ---
@app.route('/')
def index():
    # Nếu cần giao diện upload ở browser, trả test.html
    return render_template('test.html')


@app.route('/upload', methods=['POST'])
def upload_audio():
    # 1. Kiểm tra có file trong form-data không
    if 'file' not in request.files:
        return jsonify({'error': 'Không có file được tải lên'}), 400

    f = request.files['file']
    if f.filename == '':
        return jsonify({'error': 'Không có file được chọn'}), 400

    if not allowed_file(f.filename):
        return jsonify({'error': 'Định dạng file không được hỗ trợ'}), 400

    # 2. Đọc file vào memory
    try:
        audio_bytes = f.read()
        if len(audio_bytes) == 0:
            return jsonify({'error': 'File rỗng'}), 400

        ext = secure_filename(f.filename).rsplit('.', 1)[1].lower()
    except Exception as e:
        logging.error(f"[FILE] Error reading file: {e}")
        return jsonify({'error': 'Lỗi đọc file'}), 500

    # 3. Gọi Deepgram
    try:
        transcript = transcribe_with_deepgram(audio_bytes, ext)
    except RuntimeError as e:
        # Lỗi kết nối hoặc xử lý Deepgram
        return jsonify({'error': str(e)}), 502
    except Exception as e:
        logging.error(f"[TRANSCRIBE] Unexpected error: {e}")
        return jsonify({'error': 'Lỗi không xác định khi xử lý audio'}), 500

    # 4. Trả kết quả JSON
    return jsonify({'transcript': transcript}), 200


# --- Xử lý lỗi chung để luôn trả JSON ---
@app.errorhandler(RequestEntityTooLarge)
def handle_large_file(e):
    return jsonify({'error': 'File quá lớn (tối đa 5MB)'}), 413


@app.errorhandler(404)
def not_found(e):
    return jsonify({'error': 'Endpoint không tồn tại'}), 404


@app.errorhandler(405)
def method_not_allowed(e):
    return jsonify({'error': 'Phương thức không cho phép'}), 405


@app.errorhandler(500)
def internal_error(e):
    return jsonify({'error': 'Lỗi server'}), 500


if __name__ == '__main__':
    # Khi chạy local
    app.run(debug=False, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
