import os
import logging
from flask import Flask, request, jsonify, render_template
import requests
from werkzeug.utils import secure_filename
from flask_cors import CORS

# --- Thiết lập Flask ---
app = Flask(__name__, template_folder="templates")

# Giới hạn kích thước file upload (5MB)
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024  # 5 MB

# Bật CORS nếu cần (cho phép bất kỳ origin nào gọi /upload)
CORS(app, resources={r"/upload": {"origins": "*"}})

# Logging cơ bản
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# --- Hard-code API Key Deepgram tại đây ---
DEEPGRAM_API_KEY = "95e26fe061960fecb8fc532883f92af0641b89d0"


# --- Các hàm hỗ trợ ---
ALLOWED_EXTENSIONS = {'wav', 'mp3', 'm4a', 'flac'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Tạo một Session tái sử dụng để giảm overhead kết nối
dg_session = requests.Session()
dg_session.headers.update({
    'Authorization': f'Token {DEEPGRAM_API_KEY}'
})
# Chú ý: chỉ set Authorization ở đây, Content-Type sẽ set riêng dựa vào ext.

def transcribe_with_deepgram(audio_bytes: bytes, ext: str, language: str = 'vi', model: str = 'nova-2') -> str:
    """
    Gửi audio_bytes lên Deepgram và trả về transcript.
    ext: phần mở rộng file (vd: 'wav', 'mp3', ...)
    """
    headers = {
        'Content-Type': f'audio/{ext}'
    }
    try:
        resp = dg_session.post(
            'https://api.deepgram.com/v1/listen',
            headers=headers,
            data=audio_bytes,
            params={'language': language, 'model': model},
            timeout=15  # timeout 15s, chỉnh tuỳ nhu cầu
        )
    except requests.RequestException as e:
        raise RuntimeError(f"Không thể kết nối tới Deepgram: {e}")

    if resp.status_code != 200:
        raise RuntimeError(f"Deepgram trả lỗi ({resp.status_code}): {resp.text}")

    try:
        data = resp.json()
        transcript = data['results']['channels'][0]['alternatives'][0]['transcript']
    except Exception as e:
        raise RuntimeError(f"Lỗi parse JSON từ Deepgram: {e}")

    return transcript

# --- Routes ---
@app.route('/')
def index():
    # Trả về template test.html (nằm trong folder templates/)
    return render_template('test.html')


@app.route('/upload', methods=['POST'])
def upload_audio():
    # 1. Kiểm tra có file không
    if 'file' not in request.files or request.files['file'].filename == '':
        return jsonify({'error': 'Vui lòng chọn file âm thanh'}), 400

    f = request.files['file']
    filename = secure_filename(f.filename)

    # 2. Kiểm tra extension
    if not allowed_file(filename):
        return jsonify({'error': 'Chỉ chấp nhận định dạng: wav, mp3, m4a, flac'}), 400

    ext = filename.rsplit('.', 1)[-1].lower()

    # 3. Đọc toàn bộ dữ liệu audio vào RAM (in-memory)
    try:
        audio_bytes = f.read()
        if not audio_bytes:
            return jsonify({'error': 'File rỗng'}), 400
    except Exception as e:
        app.logger.error(f"Lỗi khi đọc file: {e}")
        return jsonify({'error': 'Lỗi khi đọc file'}), 500

    # 4. Gửi lên Deepgram
    try:
        transcript = transcribe_with_deepgram(audio_bytes, ext, language='vi', model='nova-2')
    except RuntimeError as e_deep:
        app.logger.error(f"Lỗi khi gọi Deepgram: {e_deep}")
        return jsonify({'error': str(e_deep)}), 502
    except Exception as e:
        app.logger.error(f"Xảy ra lỗi không xác định: {e}")
        return jsonify({'error': 'Lỗi server khi transcribe'}), 500

    # 5. Trả về transcript
    return jsonify({'transcript': transcript}), 200


if __name__ == '__main__':
    # Chạy cho môi trường development; production nên dùng Gunicorn
    app.run(debug=False, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
