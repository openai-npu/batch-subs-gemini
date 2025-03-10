#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import glob
import logging
import subprocess
import json
import threading
import time
import contextlib
import io
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QPushButton, QLabel, QLineEdit, QComboBox, QFileDialog, 
    QProgressBar, QTextEdit, QGroupBox, QTabWidget, QMessageBox,
    QCheckBox, QSpinBox
)
from PyQt6.QtCore import QThread, pyqtSignal, Qt, QSize
from PyQt6.QtGui import QIcon, QFont
import gemini_srt_translator as gst

# 자체 모듈 import (없으면 패스)
try:
    import ffmpeg_utils
    import subtitle_utils
    import logger_utils
    HAVE_UTILS = True
except ImportError:
    HAVE_UTILS = False

# 로깅 설정
if HAVE_UTILS:
    logger = logger_utils.setup_logging(
        log_level=logging.INFO,
        log_file="gemini_srt_gui.log"
    )
else:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    logger = logging.getLogger()

# 다국어 지원을 위한 번역 딕셔너리
TRANSLATIONS = {
    'en': {
        'title': 'Batch Subtitle Translator',
        'api_key': 'Gemini API Key:',
        'input_folder': 'Input Folder:',
        'browse': 'Browse',
        'model': 'Translation Model:',
        'start': 'Start Translation',
        'progress': 'Progress:',
        'log': 'Log:',
        'language': 'Language: ',
        'error_no_files': 'No MKV files found in the specified folder',
        'error_missing_fields': 'Please fill in all required fields',
        'status_processing': 'Processing file {current} of {total}',
        'status_completed': 'All files processed',
        'status_ready': 'Ready',
    },
    'ko': {
        'title': '자막 일괄 번역기',
        'api_key': 'Gemini API 키:',
        'input_folder': '입력 폴더:',
        'browse': '찾아보기',
        'model': '번역 모델:',
        'start': '번역 시작',
        'progress': '진행 상황:',
        'log': '로그:',
        'language': '언어: ',
        'error_no_files': '지정한 폴더에 MKV 파일이 없습니다',
        'error_missing_fields': '모든 필수 항목을 입력해주세요',
        'status_processing': '파일 처리 중 ({current}/{total})',
        'status_completed': '모든 파일 처리 완료',
        'status_ready': '준비',
    }
}

def extract_subtitle(mkv_file, output_srt, preferred_languages=None):
    """
    MKV 파일에서 자막을 추출합니다.
    
    Args:
        mkv_file (str): MKV 파일 경로
        output_srt (str): 출력 SRT 파일 경로
        preferred_languages (list, optional): 선호하는 언어 코드 리스트
    
    Returns:
        bool: 성공 여부
    """
    if HAVE_UTILS:
        # 새 유틸리티 사용
        return subtitle_utils.extract_subtitle(
            mkv_file, 
            output_srt, 
            track_index=None, 
            preferred_languages=preferred_languages
        )
    else:
        # 기존 방식 (fallback)
        cmd = [
            "ffmpeg", "-y", "-i", mkv_file,
            "-map", "0:s:0",  # 첫 번째 자막 트랙 선택
            "-c:s", "srt", output_srt
        ]
        try:
            subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            logging.info(f"[자막 추출 성공] {os.path.basename(mkv_file)} -> {os.path.basename(output_srt)}")
            return True
        except subprocess.CalledProcessError as e:
            err_msg = e.stderr.decode('utf-8').strip()
            logging.error(f"[자막 추출 실패] {os.path.basename(mkv_file)}: {err_msg}")
            return False
        except FileNotFoundError:
            logging.error("ffmpeg를 찾을 수 없습니다. ffmpeg를 설치하거나 PATH에 추가해주세요.")
            return False

def translate_subtitle(srt_file):
    """
    gemini_srt_translator를 사용하여 자막을 번역합니다.
    """
    # 자막 파일이 존재하는지 확인
    if not os.path.exists(srt_file):
        logging.error(f"[번역 실패] 자막 파일이 존재하지 않습니다: {srt_file}")
        return False
    
    # 자막 파일 유효성 검사 (가능한 경우)
    if HAVE_UTILS:
        valid, line_count = subtitle_utils.verify_subtitle_file(srt_file)
        if not valid:
            logging.error(f"[번역 실패] 유효하지 않은 자막 파일입니다: {srt_file} (줄 수: {line_count})")
            return False
    
    base, ext = os.path.splitext(srt_file)
    output_file = f"{base}_translated{ext}"
    gst.input_file = srt_file
    gst.output_file = output_file
    logging.info(f"[번역 시작] {os.path.basename(srt_file)} -> {os.path.basename(output_file)}")
    
    try:
        gst.translate()
        logging.info(f"[번역 완료] {os.path.basename(output_file)} 생성됨")
        return True
    except Exception as ex:
        logging.error(f"[번역 에러] {os.path.basename(srt_file)} 처리 중 에러 발생: {ex}")
        return False

# 향상된 로깅 핸들러 (기존 코드와의 호환성 유지)
class LogHandler(logging.Handler):
    def __init__(self, signal):
        super().__init__()
        self.signal = signal
        self.safe_handler = None
        
        # 새 유틸리티 사용 가능한 경우
        if HAVE_UTILS:
            self.safe_handler = logger_utils.QtLogHandler(signal)
    
    def emit(self, record):
        # 새 로깅 시스템 사용
        if self.safe_handler:
            # 이미 안전한 핸들러가 처리하므로 여기서는 아무 것도 하지 않음
            return
            
        # 레거시 방식 폴백
        try:
            msg = self.format(record)
            self.signal(msg)
        except Exception as e:
            # 오류 시 빈 함수 객체 확인
            if callable(self.signal):
                try:
                    self.signal(f"로깅 오류: {e}")
                except:
                    pass  # 마지막 시도도 실패하면 무시

class TranslationWorker(QThread):
    progress = pyqtSignal(int)
    finished = pyqtSignal()
    log = pyqtSignal(str)
    status = pyqtSignal(str)

    def __init__(self, api_key, input_folder, model):
        super().__init__()
        self.api_key = api_key
        self.input_folder = input_folder
        self.model = model
        self.is_running = True
        self.preferred_languages = ['eng', 'en']  # 영어 자막 우선
        self.log_handler = None

    def run(self):
        # 로깅 핸들러 설정
        if HAVE_UTILS:
            # 향상된 Qt 로깅 핸들러 사용
            self.log_handler = logger_utils.QtLogHandler()
            self.log_handler.connect_signal(self.log.emit)
            self.log_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
            logger.addHandler(self.log_handler)
        else:
            # 기존 로그 핸들러 사용
            self.log_handler = LogHandler(self.log.emit)
            self.log_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
            logger.addHandler(self.log_handler)
        
        try:
            # ffmpeg 확인 및 다운로드 (필요한 경우)
            if HAVE_UTILS:
                ffmpeg_path = ffmpeg_utils.get_ffmpeg_executable()
                if ffmpeg_path:
                    self.log.emit(f"ffmpeg 사용 가능: {ffmpeg_path}")
                else:
                    self.log.emit("ffmpeg를 찾을 수 없어 작업을 중단합니다.")
                    return
                    
            # Gemini 설정
            gst.gemini_api_key = self.api_key
            gst.model_name = self.model
            gst.target_language = "Korean"

            # MKV 파일 검색
            escaped_folder = glob.escape(self.input_folder)
            mkv_pattern = os.path.join(escaped_folder, "*.mkv")
            mkv_files = sorted(glob.glob(mkv_pattern))
            total_files = len(mkv_files)

            if total_files == 0:
                self.log.emit(TRANSLATIONS['ko']['error_no_files'])
                return

            self.log.emit(f"총 {total_files}개의 MKV 파일 처리 시작")

            for index, mkv_file in enumerate(mkv_files, start=1):
                if not self.is_running:
                    self.log.emit("작업이 중단되었습니다.")
                    break

                self.status.emit(TRANSLATIONS['ko']['status_processing'].format(
                    current=index, total=total_files
                ))
                self.progress.emit(int((index - 1) / total_files * 100))

                self.log.emit(f"파일 [{index}/{total_files}]: {os.path.basename(mkv_file)} 처리 시작")
                
                # 자막 정보 표시 (가능한 경우)
                if HAVE_UTILS:
                    tracks = subtitle_utils.list_subtitle_tracks(mkv_file)
                    if tracks:
                        self.log.emit(f"자막 트랙 {len(tracks)}개 발견:")
                        for i, track in enumerate(tracks):
                            self.log.emit(f"  - 트랙 #{i}: 언어={track['language']}, 코덱={track['codec']}, 제목={track.get('title', '')}")
                    else:
                        self.log.emit("자막 트랙을 찾을 수 없습니다.")

                base_name, _ = os.path.splitext(mkv_file)
                srt_file = f"{base_name}_eng.srt"

                # 자막 추출에 성공하면 번역 진행, 실패 시 해당 파일 건너뜀
                if extract_subtitle(mkv_file, srt_file, self.preferred_languages):
                    if translate_subtitle(srt_file):
                        self.log.emit(f"파일 처리 완료: {os.path.basename(mkv_file)}")
                    else:
                        self.log.emit(f"번역 실패: {os.path.basename(srt_file)}")
                else:
                    self.log.emit(f"파일 건너뜀: {os.path.basename(mkv_file)}")

                self.progress.emit(int(index / total_files * 100))

            self.status.emit(TRANSLATIONS['ko']['status_completed'])
            self.progress.emit(100)

        except Exception as e:
            self.log.emit(f"Error: {str(e)}")
        finally:
            # 로깅 핸들러 제거
            if self.log_handler:
                logger.removeHandler(self.log_handler)
                if HAVE_UTILS and hasattr(self.log_handler, 'disconnect_signal'):
                    self.log_handler.disconnect_signal(self.log.emit)
            self.finished.emit()

    def stop(self):
        self.is_running = False

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.current_language = 'ko'  # 기본 언어를 한국어로 설정
        self.init_ui()
        self.setup_logging()
        self.load_models()

    def init_ui(self):
        self.setWindowTitle(TRANSLATIONS[self.current_language]['title'])
        self.resize(800, 600)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)

        # 언어 선택
        lang_layout = QHBoxLayout()
        lang_label = QLabel(TRANSLATIONS[self.current_language]['language'])
        self.lang_combo = QComboBox()
        self.lang_combo.addItems(['English', '한국어'])
        self.lang_combo.setCurrentIndex(1)  # 한국어 선택
        self.lang_combo.currentIndexChanged.connect(self.change_language)
        lang_layout.addWidget(lang_label)
        lang_layout.addWidget(self.lang_combo)
        lang_layout.addStretch()
        layout.addLayout(lang_layout)

        # API 키 입력
        api_layout = QHBoxLayout()
        api_label = QLabel(TRANSLATIONS[self.current_language]['api_key'])
        self.api_input = QLineEdit()
        api_layout.addWidget(api_label)
        api_layout.addWidget(self.api_input)
        layout.addLayout(api_layout)

        # 입력 폴더 선택
        folder_layout = QHBoxLayout()
        folder_label = QLabel(TRANSLATIONS[self.current_language]['input_folder'])
        self.folder_input = QLineEdit()
        browse_btn = QPushButton(TRANSLATIONS[self.current_language]['browse'])
        browse_btn.clicked.connect(self.browse_folder)
        folder_layout.addWidget(folder_label)
        folder_layout.addWidget(self.folder_input)
        folder_layout.addWidget(browse_btn)
        layout.addLayout(folder_layout)

        # 모델 선택
        model_layout = QHBoxLayout()
        model_label = QLabel(TRANSLATIONS[self.current_language]['model'])
        self.model_combo = QComboBox()
        model_layout.addWidget(model_label)
        model_layout.addWidget(self.model_combo)
        layout.addLayout(model_layout)

        # 시작 버튼
        button_layout = QHBoxLayout()
        self.start_btn = QPushButton(TRANSLATIONS[self.current_language]['start'])
        self.start_btn.clicked.connect(self.start_translation)
        button_layout.addStretch()
        button_layout.addWidget(self.start_btn)
        layout.addLayout(button_layout)

        # 진행 상태바
        progress_label = QLabel(TRANSLATIONS[self.current_language]['progress'])
        self.progress_bar = QProgressBar()
        layout.addWidget(progress_label)
        layout.addWidget(self.progress_bar)

        # 상태 표시줄
        self.status_label = QLabel(TRANSLATIONS[self.current_language]['status_ready'])
        layout.addWidget(self.status_label)

        # 로그 출력
        log_label = QLabel(TRANSLATIONS[self.current_language]['log'])
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        layout.addWidget(log_label)
        layout.addWidget(self.log_output)

    def browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Input Folder")
        if folder:
            self.folder_input.setText(folder)

    def start_translation(self):
        api_key = self.api_input.text()
        input_folder = self.folder_input.text()
        model = self.model_combo.currentText()

        if not api_key or not input_folder:
            QMessageBox.warning(self, "Error", 
                              TRANSLATIONS[self.current_language]['error_missing_fields'])
            return

        self.start_btn.setEnabled(False)
        self.progress_bar.setValue(0)
        self.worker = TranslationWorker(api_key, input_folder, model)
        self.worker.progress.connect(self.progress_bar.setValue)
        self.worker.log.connect(self.log_output.append)
        self.worker.status.connect(self.status_label.setText)
        self.worker.finished.connect(self.translation_finished)
        self.worker.start()

    def translation_finished(self):
        self.start_btn.setEnabled(True)
        self.status_label.setText(TRANSLATIONS[self.current_language]['status_ready'])

    def change_language(self, index):
        self.current_language = 'en' if index == 0 else 'ko'
        self.update_texts()

    def update_texts(self):
        self.setWindowTitle(TRANSLATIONS[self.current_language]['title'])
        # 나머지 UI 요소들의 텍스트 업데이트
        self.status_label.setText(TRANSLATIONS[self.current_language]['status_ready'])

    def load_models(self):
        try:
            # 출력 캡처
            capture_output = io.StringIO()
            with contextlib.redirect_stdout(capture_output):
                gst.listmodels()
            output = capture_output.getvalue()
            
            # 빈 줄 제거하고, 각 줄의 텍스트를 모델로 간주
            models = [line.strip() for line in output.splitlines() if line.strip()]
            
            if models:
                self.model_combo.clear()
                self.model_combo.addItems(models)
        except Exception as e:
            self.log_output.append(f"모델 로드 중 오류 발생: {str(e)}")

    def setup_logging(self):
        """GUI 로깅 설정"""
        # 출력 함수
        log_output_func = lambda msg: self.log_output.append(msg)
        
        if HAVE_UTILS:
            # 향상된 로깅 사용
            self.log_handler = logger_utils.QtLogHandler(log_output_func)
            self.log_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        else:
            # 기존 로깅 사용
            self.log_handler = LogHandler(log_output_func)
            self.log_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        
        # 로거에 핸들러 추가
        logger.addHandler(self.log_handler)

def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == '__main__':
    main() 