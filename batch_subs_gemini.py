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
from PyQt6.QtCore import QThread, pyqtSignal, Qt, QSize, QMetaObject, Q_ARG
from PyQt6.QtGui import QIcon, QFont, QTextCursor
import gemini_srt_translator as gst
import platform
import traceback
import locale
from datetime import datetime

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
        log_file="batch_subs_gemini.log"
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
        'api_key2': 'Secondary API Key (Optional):',
        'input_folder': 'Input Path:',
        'browse': 'Browse',
        'model': 'Translation Model:',
        'start': 'Start Translation',
        'progress': 'Progress:',
        'log': 'Log:',
        'logs': 'Logs:',
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
        'tab_main': 'Main Features',
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
        'logs': '로그:',
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
        'tab_main': '메인 기능',
    }
}

def extract_subtitle(mkv_file, output_srt, preferred_languages=None):
    """
    MKV 파일에서 자막을 추출합니다.
    
    Args:
        mkv_file (str): MKV 파일 경로
        output_srt (str): 출력 SRT 파일 경로
        preferred_languages (list, optional): 선호하는 언어 코드 리스트. 기본값: ['eng', 'en']
    
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

# LogHandler 클래스 전체 재구현
class LogHandler(logging.Handler):
    """Qt 로그 핸들러 (일반 또는 안전한 로깅)"""
    def __init__(self, signal):
        super().__init__()
        self.signal = signal
        self.safe_handler = None
        
        # logger_utils가 있으면 안전한 로깅 설정
        if HAVE_UTILS:
            try:
                self.safe_handler = logger_utils.QtLogHandler()
                self.safe_handler.connect_signal(signal)
            except Exception as e:
                print(f"안전한 로그 핸들러 초기화 실패: {e}")
                self.safe_handler = None
    
    def emit(self, record):
        # 새 로깅 시스템 사용
        if HAVE_UTILS and self.safe_handler:
            # 안전한 로그 핸들러에 위임
            self.safe_handler.emit(record)
        else:
            # 이전 방식으로 직접 시그널 발생 (폴백)
            try:
                message = self.format(record)
                # PyQt에서 스레드 안전하게 시그널 발생
                if self.signal is not None:
                    self.signal(message)
            except Exception:
                # 로깅 중 오류가 발생해도 앱은 계속 실행
                pass

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
        self.preferred_languages = ['eng', 'en']  # 영어 자막 우선
        self.log_handler = None

    def run(self):
        # 로깅 핸들러 설정
        self.log_handler = LogHandler(self.log.emit)
        self.log_handler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
        
        # 로그 핸들러 등록 (임시 로거 사용)
        worker_logger = logging.getLogger(f"worker_{id(self)}")
        worker_logger.setLevel(logging.INFO)
        worker_logger.addHandler(self.log_handler)
        
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

            self.status.emit(TRANSLATIONS[self.current_language]['status_completed'])
            self.progress.emit(100)

        except Exception as e:
            error_msg = f"오류 발생: {str(e)}"
            logging.error(error_msg)
            self.status.emit(error_msg)
        finally:
            # 로그 핸들러 정리
            if HAVE_UTILS and self.log_handler.safe_handler:
                try:
                    self.log_handler.safe_handler.disconnect_signal(self.log.emit)
                except Exception:
                    pass
            
            # 로그 핸들러 제거
            worker_logger.removeHandler(self.log_handler)
            self.log_handler = None
            
            # 작업 완료 시그널 발생
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

        # 탭 위젯 생성
        self.tab_widget = QTabWidget()
        layout.addWidget(self.tab_widget)
        
        # 탭1 - 메인 기능
        self.tab1 = QWidget()
        self.tab1_layout = QVBoxLayout(self.tab1)
        self.tab_widget.addTab(self.tab1, TRANSLATIONS[self.current_language]['tab_main'])
        
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
        self.tab1_layout.addLayout(lang_layout)

        # API 키 입력
        api_layout = QHBoxLayout()
        self.api_label = QLabel(TRANSLATIONS[self.current_language]['api_key'])
        self.api_input = QLineEdit()
        api_layout.addWidget(self.api_label)
        api_layout.addWidget(self.api_input)
        self.tab1_layout.addLayout(api_layout)
        
        # 보조 API 키 입력
        api2_layout = QHBoxLayout()
        self.api2_label = QLabel(TRANSLATIONS[self.current_language]['api_key2'])
        self.api2_input = QLineEdit()
        api2_layout.addWidget(self.api2_label)
        api2_layout.addWidget(self.api2_input)
        self.tab1_layout.addLayout(api2_layout)

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
        self.tab1_layout.addLayout(radio_layout)

        # 입력 경로 선택
        folder_layout = QHBoxLayout()
        self.folder_label = QLabel(TRANSLATIONS[self.current_language]['input_folder'])
        self.folder_input = QLineEdit()
        self.browse_btn = QPushButton(TRANSLATIONS[self.current_language]['browse'])
        self.browse_btn.clicked.connect(self.browse_path)
        folder_layout.addWidget(self.folder_label)
        folder_layout.addWidget(self.folder_input)
        folder_layout.addWidget(self.browse_btn)
        self.tab1_layout.addLayout(folder_layout)

        # 모델 선택
        model_layout = QHBoxLayout()
        self.model_label = QLabel(TRANSLATIONS[self.current_language]['model'])
        self.model_combo = QComboBox()
        self.get_models_btn = QPushButton(TRANSLATIONS[self.current_language]['get_models'])
        self.get_models_btn.clicked.connect(self.fetch_models)
        model_layout.addWidget(self.model_label)
        model_layout.addWidget(self.model_combo)
        model_layout.addWidget(self.get_models_btn)
        self.tab1_layout.addLayout(model_layout)

        # 시작 버튼
        button_layout = QHBoxLayout()
        self.start_btn = QPushButton(TRANSLATIONS[self.current_language]['start'])
        self.start_btn.clicked.connect(self.start_translation)
        button_layout.addStretch()
        button_layout.addWidget(self.start_btn)
        self.tab1_layout.addLayout(button_layout)

        # 진행 상태바
        progress_layout = QHBoxLayout()
        self.progress_label = QLabel(TRANSLATIONS[self.current_language]['progress'])
        self.progress_bar = QProgressBar()
        progress_layout.addWidget(self.progress_label)
        progress_layout.addWidget(self.progress_bar)
        self.tab1_layout.addLayout(progress_layout)

        # 상태 표시줄
        self.status_label = QLabel(TRANSLATIONS[self.current_language]['status_ready'])
        self.tab1_layout.addWidget(self.status_label)

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
        try:
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
        except Exception as e:
            logger.error(f"모델 목록 조회 중 오류: {str(e)}")
            self.get_models_btn.setEnabled(True)
            if hasattr(self, 'log_text'):
                self.log_text.append(f"오류: {str(e)}")
            QMessageBox.critical(self, "오류", f"모델 목록 조회 중 오류 발생: {str(e)}")
    
    def on_models_loaded(self, models):
        try:
            if not hasattr(self, 'model_combo') or not self.model_combo:
                logger.error("model_combo가 초기화되지 않았습니다")
                return
                
            self.model_combo.clear()
            self.model_combo.addItems(models)
            
            if hasattr(self, 'status_label') and self.status_label:
                current_lang = getattr(self, 'current_language', 'ko')
                translations = TRANSLATIONS.get(current_lang, TRANSLATIONS['ko'])
                status_text = translations.get('models_loaded', '모델 목록 로드 완료')
                self.status_label.setText(status_text)
            
            self.get_models_btn.setEnabled(True)
            
            if hasattr(self, 'log_text'):
                current_lang = getattr(self, 'current_language', 'ko')
                translations = TRANSLATIONS.get(current_lang, TRANSLATIONS['ko'])
                log_text = translations.get('models_loaded', '모델 목록 로드 완료')
                self.log_text.append(log_text)
        except Exception as e:
            logger.error(f"모델 목록 처리 중 오류: {str(e)}")
            self.get_models_btn.setEnabled(True)
    
    def on_model_load_error(self, error_msg):
        try:
            if hasattr(self, 'status_label'):
                self.status_label.setText(TRANSLATIONS[self.current_language]['status_ready'])
            
            if hasattr(self, 'get_models_btn'):
                self.get_models_btn.setEnabled(True)
            
            if hasattr(self, 'log_text'):
                self.log_text.append(f"Error: {error_msg}")
            
            QMessageBox.warning(self, "Error", f"Failed to load models: {error_msg}")
        except Exception as e:
            logger.error(f"모델 로드 오류 처리 중 예외 발생: {str(e)}")
            QMessageBox.critical(self, "오류", f"예기치 않은 오류가 발생했습니다: {str(e)}")

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
        self.worker.log.connect(self.log_text.append)
        self.worker.status.connect(self.status_label.setText)
        self.worker.finished.connect(self.translation_finished)
        self.worker.start()

    def translation_finished(self):
        self.start_btn.setEnabled(True)
        self.status_label.setText(TRANSLATIONS[self.current_language]['status_ready'])

    def change_language(self, index):
        try:
            self.current_language = 'en' if index == 0 else 'ko'
            self.update_texts()
        except Exception as e:
            logger.error(f"언어 변경 중 오류: {str(e)}")
            QMessageBox.critical(self, "오류", f"언어 변경 중 오류 발생: {str(e)}")
            # 언어 설정을 기본값으로 복원
            self.current_language = 'ko'
            if hasattr(self, 'lang_combo') and self.lang_combo:
                self.lang_combo.setCurrentIndex(1)  # 한국어 선택

    def update_texts(self):
        try:
            # 윈도우 타이틀 업데이트
            self.setWindowTitle(TRANSLATIONS[self.current_language]['title'])
            
            # 레이블 업데이트
            if hasattr(self, 'api_label') and self.api_label:
                self.api_label.setText(TRANSLATIONS[self.current_language]['api_key'])
            if hasattr(self, 'api2_label') and self.api2_label:
                self.api2_label.setText(TRANSLATIONS[self.current_language]['api_key2'])
            if hasattr(self, 'folder_label') and self.folder_label:
                self.folder_label.setText(TRANSLATIONS[self.current_language]['input_folder'])
            if hasattr(self, 'model_label') and self.model_label:
                self.model_label.setText(TRANSLATIONS[self.current_language]['model'])
            if hasattr(self, 'progress_label') and self.progress_label:
                self.progress_label.setText(TRANSLATIONS[self.current_language]['progress'])
            if hasattr(self, 'log_label') and self.log_label:
                self.log_label.setText(TRANSLATIONS[self.current_language]['log'])
            
            # 버튼 텍스트 업데이트
            if hasattr(self, 'start_btn') and self.start_btn:
                self.start_btn.setText(TRANSLATIONS[self.current_language]['start'])
            if hasattr(self, 'browse_btn') and self.browse_btn:
                self.browse_btn.setText(TRANSLATIONS[self.current_language]['browse'])
            if hasattr(self, 'get_models_btn') and self.get_models_btn:
                self.get_models_btn.setText(TRANSLATIONS[self.current_language]['get_models'])
            
            # 탭 타이틀 업데이트
            if hasattr(self, 'tab_widget') and self.tab_widget and hasattr(self, 'tab1'):
                self.tab_widget.setTabText(0, TRANSLATIONS[self.current_language]['tab_main'])
                
            # 라디오 버튼 업데이트
            if hasattr(self, 'folder_radio') and self.folder_radio:
                self.folder_radio.setText(TRANSLATIONS[self.current_language]['folder_option'])
            if hasattr(self, 'file_radio') and self.file_radio:
                self.file_radio.setText(TRANSLATIONS[self.current_language]['file_option'])
            
            # 상태 레이블 업데이트
            if hasattr(self, 'status_label') and self.status_label:
                self.status_label.setText(TRANSLATIONS[self.current_language]['status_ready'])
        except Exception as e:
            logger.error(f"텍스트 업데이트 중 오류: {str(e)}")
            # 오류 발생 시 기본값으로 복원
            self.current_language = 'ko'

    def setup_logging(self):
        """로깅 설정"""
        # 로그 출력용 텍스트 에디터
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        # log_output 변수가 많은 곳에서 사용되고 있으므로 log_text에 대한 별칭으로 추가
        self.log_output = self.log_text
        # 윈도우와의 호환성을 위해 setMaximumBlockCount 대신 다른 방식으로 크기 제한
        # self.log_text.setMaximumBlockCount(1000)  # 로그 항목 수 제한
        
        # 로그 처리 함수
        def append_log(message):
            try:
                # 메인 스레드에서 실행 중인지 확인
                if QThread.currentThread() == QApplication.instance().thread():
                    # 직접 로그 추가
                    self.log_text.append(message)
                    
                    # 문서 크기 제한 (1000줄로 제한)
                    doc = self.log_text.document()
                    if doc.blockCount() > 1000:
                        # 초과분을 제거하기 위한 커서 설정
                        cursor = QTextCursor(doc)
                        cursor.movePosition(QTextCursor.MoveOperation.Start)
                        cursor.movePosition(
                            QTextCursor.MoveOperation.Down,
                            QTextCursor.MoveMode.KeepAnchor, 
                            doc.blockCount() - 1000
                        )
                        cursor.removeSelectedText()
                else:
                    # 다른 스레드에서 호출된 경우, 메인 스레드로 전달
                    QMetaObject.invokeMethod(
                        self.log_text, 
                        "append", 
                        Qt.ConnectionType.QueuedConnection,
                        Q_ARG(str, message)
                    )
            except:
                # 로그 표시 중 오류가 발생해도 앱은 계속 실행
                pass
        
        # 로그 핸들러 생성 및 설정
        self.log_handler = LogHandler(append_log)
        self.log_handler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
        
        # 로그 핸들러 등록
        logger = logging.getLogger()
        logger.addHandler(self.log_handler)
        
        # UI에 로그 창 추가 (tab1_layout이 있는 경우에만)
        if hasattr(self, 'tab1_layout'):
            self.tab1_layout.addWidget(QLabel(TRANSLATIONS[self.current_language]['logs']))
            self.tab1_layout.addWidget(self.log_text)
        else:
            # 중앙 위젯에 직접 추가
            layout = self.centralWidget().layout()
            if layout:
                log_group = QGroupBox(TRANSLATIONS[self.current_language]['logs'])
                log_layout = QVBoxLayout(log_group)
                log_layout.addWidget(self.log_text)
                layout.addWidget(log_group)

def log_debug_info():
    """앱 시작 시 디버그 정보를 로깅"""
    try:
        # 로그 파일 경로 설정
        log_dir = os.path.expanduser("~/Documents")
        if not os.path.exists(log_dir):
            log_dir = tempfile.gettempdir()
            
        log_path = os.path.join(log_dir, "debug_startup.log")
        
        with open(log_path, "w", encoding="utf-8") as f:
            # 시스템 정보
            f.write(f"==== 앱 시작 디버그 로그 ({datetime.now()}) ====\n")
            f.write(f"Python 버전: {sys.version}\n")
            f.write(f"플랫폼: {sys.platform}\n")
            f.write(f"OS: {platform.platform()}\n")
            f.write(f"Locale: {locale.getdefaultlocale()}\n")
            
            # 경로 정보
            f.write(f"실행 파일: {sys.executable}\n")
            f.write(f"작업 디렉토리: {os.getcwd()}\n")
            f.write(f"sys.path: {sys.path}\n")
            
            # 모듈 로딩 시도
            f.write("\n==== 모듈 로딩 시도 ====\n")
            modules_to_check = [
                "PyQt6", "google.generativeai", "gemini-api", 
                "openai", "ffmpeg", "srt", "logger_utils"
            ]
            
            for module in modules_to_check:
                try:
                    __import__(module)
                    f.write(f"{module}: 성공\n")
                except ImportError as e:
                    f.write(f"{module}: 실패 - {e}\n")
                except Exception as e:
                    f.write(f"{module}: 오류 - {e}\n")
            
            # 환경 변수
            f.write("\n==== 환경 변수 ====\n")
            for key, value in os.environ.items():
                if key.startswith(("PYTHONH", "QT_", "PATH", "PYTHONP", "LANG")):
                    f.write(f"{key}: {value}\n")
    except Exception as e:
        print(f"디버그 정보 로깅 실패: {e}")

def main():
    """애플리케이션 메인 함수"""
    try:
        # 시작 시 디버그 정보 로깅
        log_debug_info()
        print("애플리케이션 시작 중...")
        
        # QApplication 인스턴스 생성
        from PyQt6.QtWidgets import QApplication
        app = QApplication(sys.argv)
        print("QApplication 인스턴스 생성 완료")
        
        # 아이콘 설정 (존재하는 경우)
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons", "icon.svg")
        if os.path.exists(icon_path):
            print(f"아이콘 로딩: {icon_path}")
            app.setWindowIcon(QIcon(icon_path))
        else:
            print(f"아이콘 파일이 존재하지 않음: {icon_path}")
        
        print("메인 윈도우 생성 중...")
        window = MainWindow()
        print("메인 윈도우 생성 완료")
        
        window.show()
        print("메인 윈도우 표시됨")
        
        print("이벤트 루프 시작")
        return app.exec()  # main 함수가 app.exec()의 결과를 반환
    except Exception as e:
        # 치명적 오류 로깅
        error_traceback = traceback.format_exc()
        error_message = f"치명적 오류: {str(e)}\n{error_traceback}"
        print(error_message)
        
        try:
            # 오류 로그 파일에 기록
            log_dir = os.path.expanduser("~/Documents")
            if not os.path.exists(log_dir):
                log_dir = tempfile.gettempdir()
                
            error_log_path = os.path.join(log_dir, "batch_subs_error.log")
            
            with open(error_log_path, "w", encoding="utf-8") as f:
                f.write(f"오류 발생 시간: {datetime.now()}\n")
                f.write(error_message)
            
            # 가능하면 메시지 박스 표시
            try:
                # 명시적으로 QApplication과 QMessageBox를 여기서 임포트
                from PyQt6.QtWidgets import QApplication, QMessageBox
                
                # 기존 QApplication 인스턴스가 있으면 사용, 없으면 새로 생성
                app = QApplication.instance()
                if app is None:
                    app = QApplication(sys.argv)
                    
                msg_box = QMessageBox()
                msg_box.setIcon(QMessageBox.Icon.Critical)
                msg_box.setWindowTitle("오류 발생")
                msg_box.setText(f"애플리케이션 시작 중 오류가 발생했습니다.\n오류 로그가 {error_log_path}에 저장되었습니다.")
                msg_box.setDetailedText(error_message)
                msg_box.exec()
            except Exception as msg_error:
                print(f"메시지 박스 표시 중 오류: {msg_error}")
        except Exception as log_error:
            print(f"오류 로깅 중 추가 오류: {log_error}")
        
        return 1

if __name__ == "__main__":
    sys.exit(main()) 