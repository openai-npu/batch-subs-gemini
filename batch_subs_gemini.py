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
import tempfile
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QPushButton, QLabel, QLineEdit, QComboBox, QFileDialog, 
    QProgressBar, QTextEdit, QGroupBox, QTabWidget, QMessageBox,
    QCheckBox, QSpinBox, QRadioButton, QButtonGroup
)
from PyQt6.QtCore import QThread, pyqtSignal, Qt, QSize
from PyQt6.QtGui import QIcon, QFont
import gemini_srt_translator as gst

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt='%Y-%m-%d %H:%M:%S'
)

# 다국어 지원을 위한 번역 딕셔너리
TRANSLATIONS = {
    'en': {
        'title': 'Batch Subtitle Translator',
        'api_key': 'Gemini API Key:',
        'api_key2': 'Secondary API Key (Optional):',
        'input_folder': 'Input Path:',
        'browse': 'Browse',
        'model': 'Translation Model:',
        'start': 'Start Translation',
        'progress': 'Progress:',
        'log': 'Log:',
        'language': 'Language: ',
        'select_folder': 'Select a folder',
        'select_file': 'Select a file',
        'folder_option': 'Process all files in folder',
        'file_option': 'Process single file',
        'error_no_files': 'No MKV files found in the specified path',
        'error_missing_fields': 'Please fill in all required fields',
        'error_no_api_key': 'Please enter API key first',
        'get_models': 'Get Models',
        'status_processing': 'Processing file {current} of {total}',
        'status_completed': 'All files processed',
        'status_ready': 'Ready',
        'loading_models': 'Loading models...',
        'models_loaded': 'Models loaded successfully',
    },
    'ko': {
        'title': '자막 일괄 번역기',
        'api_key': 'Gemini API 키:',
        'api_key2': '보조 API 키 (선택사항):',
        'input_folder': '입력 경로:',
        'browse': '찾아보기',
        'model': '번역 모델:',
        'start': '번역 시작',
        'progress': '진행 상황:',
        'log': '로그:',
        'language': '언어: ',
        'select_folder': '폴더 선택',
        'select_file': '파일 선택',
        'folder_option': '폴더 내 모든 파일 처리',
        'file_option': '단일 파일 처리',
        'error_no_files': '지정한 경로에 MKV 파일이 없습니다',
        'error_missing_fields': '모든 필수 항목을 입력해주세요',
        'error_no_api_key': 'API 키를 먼저 입력해주세요',
        'get_models': '모델 목록 조회',
        'status_processing': '파일 처리 중 ({current}/{total})',
        'status_completed': '모든 파일 처리 완료',
        'status_ready': '준비',
        'loading_models': '모델 목록 로딩 중...',
        'models_loaded': '모델 목록 로드 완료',
    }
}

def extract_subtitle(mkv_file, output_srt):
    """
    ffmpeg를 이용하여 MKV 파일에서 첫 번째 자막 트랙을 추출합니다.
    """
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

def translate_subtitle(srt_file):
    """
    gemini_srt_translator를 사용하여 자막을 번역합니다.
    """
    base, ext = os.path.splitext(srt_file)
    output_file = f"{base}_translated{ext}"
    gst.input_file = srt_file
    gst.output_file = output_file
    logging.info(f"[번역 시작] {os.path.basename(srt_file)} -> {os.path.basename(output_file)}")
    try:
        gst.translate()
        logging.info(f"[번역 완료] {os.path.basename(output_file)} 생성됨")
    except Exception as ex:
        logging.error(f"[번역 에러] {os.path.basename(srt_file)} 처리 중 에러 발생: {ex}")

class LogHandler(logging.Handler):
    def __init__(self, signal):
        super().__init__()
        self.signal = signal

    def emit(self, record):
        msg = self.format(record)
        self.signal.emit(msg)

class ModelLoaderWorker(QThread):
    models_loaded = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, api_key):
        super().__init__()
        self.api_key = api_key
        
    def run(self):
        try:
            # 임시로 API 키 설정
            orig_api_key = gst.gemini_api_key
            gst.gemini_api_key = self.api_key
            
            # 출력 캡처
            capture_output = io.StringIO()
            with contextlib.redirect_stdout(capture_output):
                gst.listmodels()
            output = capture_output.getvalue()
            
            # 빈 줄 제거하고, 각 줄의 텍스트를 모델로 간주
            models = [line.strip() for line in output.splitlines() if line.strip()]
            
            # 원래 API 키 복원
            gst.gemini_api_key = orig_api_key
            
            if models:
                self.models_loaded.emit(models)
            else:
                self.error.emit("No models found")
        except Exception as e:
            self.error.emit(str(e))

class TranslationWorker(QThread):
    progress = pyqtSignal(int)
    finished = pyqtSignal()
    log = pyqtSignal(str)
    status = pyqtSignal(str)

    def __init__(self, api_key, api_key2, input_path, model, is_folder=True, current_language='ko'):
        super().__init__()
        self.api_key = api_key
        self.api_key2 = api_key2
        self.input_path = input_path
        self.model = model
        self.is_folder = is_folder
        self.is_running = True
        self.current_language = current_language

    def run(self):
        # 로깅 핸들러 설정
        handler = LogHandler(self.log)
        handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        logging.getLogger().addHandler(handler)
        
        try:
            # Gemini 설정
            gst.gemini_api_key = self.api_key
            gst.gemini_api_key2 = self.api_key2
            gst.model_name = self.model
            gst.target_language = "Korean"

            # 처리할 파일 목록 결정
            mkv_files = []
            if self.is_folder:
                # 폴더 내 모든 MKV 파일 처리
                escaped_folder = glob.escape(self.input_path)
                mkv_pattern = os.path.join(escaped_folder, "*.mkv")
                mkv_files = sorted(glob.glob(mkv_pattern))
            else:
                # 단일 파일 처리
                if self.input_path.lower().endswith('.mkv'):
                    mkv_files = [self.input_path]
            
            total_files = len(mkv_files)

            if total_files == 0:
                self.log.emit(TRANSLATIONS[self.current_language]['error_no_files'])
                return

            self.log.emit(f"총 {total_files}개의 MKV 파일 처리 시작")

            for index, mkv_file in enumerate(mkv_files, start=1):
                if not self.is_running:
                    self.log.emit("작업이 중단되었습니다.")
                    break

                self.status.emit(TRANSLATIONS[self.current_language]['status_processing'].format(
                    current=index, total=total_files
                ))
                self.progress.emit(int((index - 1) / total_files * 100))

                self.log.emit(f"파일 [{index}/{total_files}]: {os.path.basename(mkv_file)} 처리 시작")

                base_name, _ = os.path.splitext(mkv_file)
                srt_file = f"{base_name}_eng.srt"

                if extract_subtitle(mkv_file, srt_file):
                    translate_subtitle(srt_file)
                else:
                    self.log.emit(f"파일 건너뜀: {os.path.basename(mkv_file)}")

                self.progress.emit(int(index / total_files * 100))

            self.status.emit(TRANSLATIONS[self.current_language]['status_completed'])
            self.progress.emit(100)

        except Exception as e:
            self.log.emit(f"Error: {str(e)}")
        finally:
            logging.getLogger().removeHandler(handler)
            self.finished.emit()

    def stop(self):
        self.is_running = False

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.current_language = 'ko'  # 기본 언어를 한국어로 설정
        self.is_folder_mode = True  # 기본으로 폴더 모드 선택
        self.init_ui()
        self.setup_logging()
        # 시작 시 모델 로드하지 않음

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
        self.api_label = QLabel(TRANSLATIONS[self.current_language]['api_key'])
        self.api_input = QLineEdit()
        api_layout.addWidget(self.api_label)
        api_layout.addWidget(self.api_input)
        layout.addLayout(api_layout)
        
        # 보조 API 키 입력
        api2_layout = QHBoxLayout()
        self.api2_label = QLabel(TRANSLATIONS[self.current_language]['api_key2'])
        self.api2_input = QLineEdit()
        api2_layout.addWidget(self.api2_label)
        api2_layout.addWidget(self.api2_input)
        layout.addLayout(api2_layout)

        # 폴더/파일 선택 라디오 버튼
        radio_layout = QHBoxLayout()
        self.folder_radio = QRadioButton(TRANSLATIONS[self.current_language]['folder_option'])
        self.file_radio = QRadioButton(TRANSLATIONS[self.current_language]['file_option'])
        self.folder_radio.setChecked(True)
        radio_group = QButtonGroup(self)
        radio_group.addButton(self.folder_radio)
        radio_group.addButton(self.file_radio)
        self.folder_radio.toggled.connect(self.toggle_input_mode)
        radio_layout.addWidget(self.folder_radio)
        radio_layout.addWidget(self.file_radio)
        radio_layout.addStretch()
        layout.addLayout(radio_layout)

        # 입력 경로 선택
        folder_layout = QHBoxLayout()
        self.folder_label = QLabel(TRANSLATIONS[self.current_language]['input_folder'])
        self.folder_input = QLineEdit()
        self.browse_btn = QPushButton(TRANSLATIONS[self.current_language]['browse'])
        self.browse_btn.clicked.connect(self.browse_path)
        folder_layout.addWidget(self.folder_label)
        folder_layout.addWidget(self.folder_input)
        folder_layout.addWidget(self.browse_btn)
        layout.addLayout(folder_layout)

        # 모델 선택
        model_layout = QHBoxLayout()
        self.model_label = QLabel(TRANSLATIONS[self.current_language]['model'])
        self.model_combo = QComboBox()
        self.get_models_btn = QPushButton(TRANSLATIONS[self.current_language]['get_models'])
        self.get_models_btn.clicked.connect(self.fetch_models)
        model_layout.addWidget(self.model_label)
        model_layout.addWidget(self.model_combo)
        model_layout.addWidget(self.get_models_btn)
        layout.addLayout(model_layout)

        # 시작 버튼
        button_layout = QHBoxLayout()
        self.start_btn = QPushButton(TRANSLATIONS[self.current_language]['start'])
        self.start_btn.clicked.connect(self.start_translation)
        button_layout.addStretch()
        button_layout.addWidget(self.start_btn)
        layout.addLayout(button_layout)

        # 진행 상태바
        progress_layout = QHBoxLayout()
        self.progress_label = QLabel(TRANSLATIONS[self.current_language]['progress'])
        self.progress_bar = QProgressBar()
        progress_layout.addWidget(self.progress_label)
        progress_layout.addWidget(self.progress_bar)
        layout.addLayout(progress_layout)

        # 상태 표시줄
        self.status_label = QLabel(TRANSLATIONS[self.current_language]['status_ready'])
        layout.addWidget(self.status_label)

        # 로그 출력
        log_layout = QVBoxLayout()
        self.log_label = QLabel(TRANSLATIONS[self.current_language]['log'])
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        log_layout.addWidget(self.log_label)
        log_layout.addWidget(self.log_output)
        layout.addLayout(log_layout)

    def toggle_input_mode(self, checked):
        if checked:  # 폴더 모드
            self.is_folder_mode = True
        else:  # 파일 모드
            self.is_folder_mode = False
    
    def browse_path(self):
        if self.is_folder_mode:
            folder = QFileDialog.getExistingDirectory(
                self,
                TRANSLATIONS[self.current_language]['select_folder']
            )
            if folder:
                self.folder_input.setText(folder)
        else:
            file, _ = QFileDialog.getOpenFileName(
                self,
                TRANSLATIONS[self.current_language]['select_file'],
                "",
                "MKV Files (*.mkv);;All Files (*)"
            )
            if file:
                self.folder_input.setText(file)

    def fetch_models(self):
        api_key = self.api_input.text()
        if not api_key:
            QMessageBox.warning(
                self, 
                "Error", 
                TRANSLATIONS[self.current_language]['error_no_api_key']
            )
            return
        
        self.status_label.setText(TRANSLATIONS[self.current_language]['loading_models'])
        self.get_models_btn.setEnabled(False)
        
        # 모델 로드 스레드 시작
        self.model_loader = ModelLoaderWorker(api_key)
        self.model_loader.models_loaded.connect(self.on_models_loaded)
        self.model_loader.error.connect(self.on_model_load_error)
        self.model_loader.start()
    
    def on_models_loaded(self, models):
        self.model_combo.clear()
        self.model_combo.addItems(models)
        self.status_label.setText(TRANSLATIONS[self.current_language]['models_loaded'])
        self.get_models_btn.setEnabled(True)
        self.log_output.append(TRANSLATIONS[self.current_language]['models_loaded'])
    
    def on_model_load_error(self, error_msg):
        self.status_label.setText(TRANSLATIONS[self.current_language]['status_ready'])
        self.get_models_btn.setEnabled(True)
        self.log_output.append(f"Error: {error_msg}")
        QMessageBox.warning(self, "Error", f"Failed to load models: {error_msg}")

    def start_translation(self):
        api_key = self.api_input.text()
        api_key2 = self.api2_input.text()
        input_path = self.folder_input.text()
        model = self.model_combo.currentText() if self.model_combo.count() > 0 else ""

        if not api_key or not input_path or not model:
            QMessageBox.warning(self, "Error", 
                              TRANSLATIONS[self.current_language]['error_missing_fields'])
            return

        self.start_btn.setEnabled(False)
        self.progress_bar.setValue(0)
        self.worker = TranslationWorker(
            api_key, 
            api_key2, 
            input_path, 
            model, 
            self.is_folder_mode,
            self.current_language
        )
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
        # 윈도우 타이틀 업데이트
        self.setWindowTitle(TRANSLATIONS[self.current_language]['title'])
        
        # 레이블 업데이트
        self.api_label.setText(TRANSLATIONS[self.current_language]['api_key'])
        self.api2_label.setText(TRANSLATIONS[self.current_language]['api_key2'])
        self.folder_label.setText(TRANSLATIONS[self.current_language]['input_folder'])
        self.model_label.setText(TRANSLATIONS[self.current_language]['model'])
        self.progress_label.setText(TRANSLATIONS[self.current_language]['progress'])
        self.log_label.setText(TRANSLATIONS[self.current_language]['log'])
        
        # 버튼 텍스트 업데이트
        self.start_btn.setText(TRANSLATIONS[self.current_language]['start'])
        self.browse_btn.setText(TRANSLATIONS[self.current_language]['browse'])
        self.get_models_btn.setText(TRANSLATIONS[self.current_language]['get_models'])
        
        # 라디오 버튼 업데이트
        self.folder_radio.setText(TRANSLATIONS[self.current_language]['folder_option'])
        self.file_radio.setText(TRANSLATIONS[self.current_language]['file_option'])
        
        # 상태 레이블 업데이트
        self.status_label.setText(TRANSLATIONS[self.current_language]['status_ready'])

    def setup_logging(self):
        self.logger = logging.getLogger()
        self.log_handler = LogHandler(lambda msg: self.log_output.append(msg))
        self.log_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        self.logger.addHandler(self.log_handler)

def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == '__main__':
    main() 