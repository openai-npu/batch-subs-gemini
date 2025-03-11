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
    QCheckBox, QSpinBox, QStatusBar
)
from PyQt6.QtCore import QThread, pyqtSignal, Qt, QSize, QMetaObject, Q_ARG
from PyQt6.QtGui import QIcon, QFont, QTextCursor
import gemini_srt_translator as gst
import platform
import tempfile
import traceback
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
        'error_no_api_key': 'Please enter the API key first',
        'loading_models': 'Loading model list...',
        'models_loaded': 'Model list loaded',
        'status_error': 'Error',
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
        'error_no_api_key': '먼저 API 키를 입력해주세요',
        'loading_models': '모델 목록 로딩 중...',
        'models_loaded': '모델 목록 로드 완료',
        'status_error': '오류 발생',
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
    """메인 윈도우 클래스"""
    def __init__(self):
        try:
            print("MainWindow 초기화 시작...")
            super().__init__()
            
            # 기본 UI 구성요소 설정
            print("UI 구성 설정 중...")
            self.setWindowTitle("Gemini-SRT 번역기")
            self.setMinimumSize(800, 600)
            
            # 메인 위젯 및 레이아웃 설정
            self.main_widget = QWidget()
            self.setCentralWidget(self.main_widget)
            self.main_layout = QVBoxLayout(self.main_widget)
            
            # 메뉴바 설정
            self.setup_menu()
            print("메뉴 설정 완료")
            
            # 상태바 설정
            self.status_bar = QStatusBar()
            self.setStatusBar(self.status_bar)
            
            # 로그 창과 로깅 설정
            print("로깅 설정 중...")
            self.setup_logging()
            print("로깅 설정 완료")
            
            # 폰트 설정
            self.setup_fonts()
            
            # 중앙 레이아웃 설정 (탭 추가)
            self.setup_tabs()
            print("탭 설정 완료")
            
            # 번역 모델 설정
            print("번역 모델 로딩 중...")
            self.setup_translation_model()
            print("번역 모델 로딩 완료")
            
            # 모델 선택 콤보박스 설정 (모델이 준비된 후 설정해야 함)
            self.setup_model_selection()
            
            # 윈도우 위치 및 크기 복원
            self.restore_window_state()
            
            # 작업자 스레드 준비
            self.worker = None
            self.worker_thread = None
            
            # 프로그레스바 설정
            self.progress_bar = QProgressBar()
            self.status_bar.addPermanentWidget(self.progress_bar)
            self.progress_bar.setVisible(False)
            
            print("MainWindow 초기화 완료")
        except Exception as e:
            print(f"MainWindow 초기화 중 오류 발생: {e}")
            # 디버그 로그에 오류 기록 시도
            try:
                debug_log_path = os.path.expanduser("~/Documents/gui_init_error.log")
                with open(debug_log_path, "w", encoding="utf-8") as f:
                    f.write(f"초기화 오류 시간: {datetime.now()}\n")
                    f.write(f"오류: {str(e)}\n")
                    f.write(traceback.format_exc())
            except:
                pass
            # 예외를 다시 발생시켜 메인에서 처리하도록 함
            raise

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
        log_layout = QVBoxLayout()
        log_layout.addWidget(QLabel(TRANSLATIONS[self.current_language]['log']))
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.log_text.setMaximumBlockCount(1000)  # 로그 항목 수 제한
        log_layout.addWidget(self.log_text)
        layout.addLayout(log_layout)

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
            if hasattr(self, 'lang_combo'):
                self.lang_combo.setCurrentIndex(1)  # 한국어 선택

    def update_texts(self):
        try:
            # 안전하게 번역 텍스트 가져오기
            def safe_get_text(key, default=""):
                try:
                    return self.get_translation(key)
                except Exception:
                    return default
            
            # 윈도우 타이틀 업데이트
            self.setWindowTitle(safe_get_text('title', 'SRT 번역기'))
            
            # 각 UI 요소 업데이트 - 요소가 존재하는지 확인 후 진행
            if hasattr(self, 'api_label'):
                self.api_label.setText(safe_get_text('api_key', 'API 키:'))
            
            if hasattr(self, 'srt_label'):
                self.srt_label.setText(safe_get_text('srt_file', 'SRT 파일:'))
            
            if hasattr(self, 'model_label'):
                self.model_label.setText(safe_get_text('model', '번역 모델:'))
            
            if hasattr(self, 'browse_btn'):
                self.browse_btn.setText(safe_get_text('browse', '찾아보기'))
            
            if hasattr(self, 'translate_btn'):
                self.translate_btn.setText(safe_get_text('translate', '번역'))
            
            if hasattr(self, 'get_models_btn'):
                self.get_models_btn.setText(safe_get_text('get_models', '모델 목록 조회'))
            
            # 탭 이름 업데이트
            if hasattr(self, 'tab_widget'):
                for i, key in enumerate(['tab_main', 'tab_settings']):
                    if i < self.tab_widget.count():
                        self.tab_widget.setTabText(i, safe_get_text(key, f'탭 {i+1}'))
            
            # 상태 표시줄 업데이트
            if hasattr(self, 'status_label'):
                self.status_label.setText(safe_get_text('status_ready', '준비됨'))
            
        except Exception as e:
            logger.error(f"텍스트 업데이트 중 오류: {str(e)}")
            # 기본 언어로 복원
            self.current_language = 'ko'

    # 번역 텍스트를 안전하게 가져오는 헬퍼 메서드 추가
    def get_translation(self, key, default=None):
        try:
            value = TRANSLATIONS.get(self.current_language, {}).get(key)
            if value is None and default is not None:
                return default
            return value or key
        except Exception:
            return default or key

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
            self.log_text.append(f"모델 로드 중 오류 발생: {str(e)}")

    def setup_logging(self):
        """로깅 설정"""
        # 로그 출력 텍스트 창 생성
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        
        # log_output 변수가 많은 곳에서 사용되고 있으므로 log_text에 대한 별칭으로 추가
        self.log_output = self.log_text
        
        # 로그 창 설정
        log_layout = QVBoxLayout()
        log_label = QLabel(TRANSLATIONS[self.current_language]['log'])
        log_layout.addWidget(log_label)
        log_layout.addWidget(self.log_text)
        
        # 로그 처리 함수 정의
        def append_log(message):
            try:
                # 메인 스레드에서 실행 중인지 확인
                if QThread.currentThread() == QApplication.instance().thread():
                    # 메인 스레드면 직접 추가
                    self.log_text.append(message)
                    
                    # 문서 크기 제한 (1000줄로 제한)
                    doc = self.log_text.document()
                    if doc.blockCount() > 1000:
                        # 초과분 제거
                        cursor = QTextCursor(doc)
                        cursor.movePosition(QTextCursor.MoveOperation.Start)
                        cursor.movePosition(
                            QTextCursor.MoveOperation.Down,
                            QTextCursor.MoveMode.KeepAnchor, 
                            doc.blockCount() - 1000
                        )
                        cursor.removeSelectedText()
                else:
                    # 다른 스레드면 메인 스레드로 전달
                    QMetaObject.invokeMethod(
                        self.log_text,
                        "append",
                        Qt.ConnectionType.QueuedConnection,
                        Q_ARG(str, message)
                    )
            except Exception as e:
                print(f"로그 표시 중 오류: {str(e)}")
                # 오류가 발생해도 앱 실행 유지
                pass
                
        # 로그 핸들러 생성 및 설정
        self.log_handler = LogHandler(append_log)
        self.log_handler.setFormatter(logging.Formatter('%(message)s'))
        logger.addHandler(self.log_handler)
        
        return log_layout

    def fetch_models(self):
        try:
            api_key = self.api_input.text()
            if not api_key:
                QMessageBox.warning(
                    self, 
                    "Error", 
                    self.get_translation('error_no_api_key', '먼저 API 키를 입력해주세요')
                )
                return
            
            self.status_label.setText(self.get_translation('loading_models', '모델 목록 로딩 중...'))
            self.get_models_btn.setEnabled(False)
            
            # 모델 로드 스레드 시작
            self.model_loader = ModelLoaderWorker(api_key)
            self.model_loader.models_loaded.connect(self.on_models_loaded)
            self.model_loader.error.connect(self.on_model_load_error)
            self.model_loader.start()
        except Exception as e:
            logger.error(f"모델 목록 조회 중 오류: {str(e)}")
            if hasattr(self, 'get_models_btn'):
                self.get_models_btn.setEnabled(True)
            if hasattr(self, 'log_output'):
                self.log_output.append(f"오류: {str(e)}")
            QMessageBox.critical(self, "오류", f"모델 목록 조회 중 오류 발생: {str(e)}")
    
    def on_models_loaded(self, models):
        try:
            if not hasattr(self, 'model_combo') or not self.model_combo:
                logger.error("model_combo가 초기화되지 않았습니다")
                return
                
            self.model_combo.clear()
            self.model_combo.addItems(models)
            
            if hasattr(self, 'status_label') and self.status_label:
                self.status_label.setText(self.get_translation('models_loaded', '모델 목록 로드 완료'))
            
            if hasattr(self, 'get_models_btn'):
                self.get_models_btn.setEnabled(True)
            
            if hasattr(self, 'log_text'):
                self.log_text.append(self.get_translation('models_loaded', '모델 목록 로드 완료'))
        except Exception as e:
            logger.error(f"모델 목록 처리 중 오류: {str(e)}")
            if hasattr(self, 'get_models_btn'):
                self.get_models_btn.setEnabled(True)
    
    def on_model_load_error(self, error_msg):
        try:
            if hasattr(self, 'status_label'):
                self.status_label.setText(self.get_translation('status_error', '오류 발생'))
            
            if hasattr(self, 'get_models_btn'):
                self.get_models_btn.setEnabled(True)
            
            if hasattr(self, 'log_output'):
                self.log_output.append(f"Error: {error_msg}")
            
            QMessageBox.warning(self, "Error", error_msg)
        except Exception as e:
            logger.error(f"모델 로드 오류 처리 중 예외 발생: {str(e)}")
            QMessageBox.critical(self, "오류", f"예기치 않은 오류가 발생했습니다: {str(e)}")

def main():
    """애플리케이션 메인 함수"""
    print(f"애플리케이션 시작: {datetime.now()}")
    print(f"Python 버전: {sys.version}")
    print(f"플랫폼: {sys.platform}")
    
    try:
        # QApplication 인스턴스 생성
        print("QApplication 생성 중...")
        app = QApplication(sys.argv)
        print("QApplication 생성 완료")
        
        # 아이콘 설정 시도
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons", "icon.svg")
        if os.path.exists(icon_path):
            print(f"아이콘 로딩: {icon_path}")
            app.setWindowIcon(QIcon(icon_path))
        else:
            print(f"아이콘 파일 없음: {icon_path}")
        
        # 메인 윈도우 생성
        print("메인 윈도우 생성 중...")
        window = MainWindow()
        print("메인 윈도우 생성 완료")
        
        # 애플리케이션 보여주기
        print("윈도우 표시 중...")
        window.show()
        print("윈도우 표시 완료")
        
        # 이벤트 루프 시작
        print("이벤트 루프 시작")
        return app.exec()
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
                
            error_log_path = os.path.join(log_dir, "gemini_srt_error.log")
            
            with open(error_log_path, "w", encoding="utf-8") as f:
                f.write(f"오류 발생 시간: {datetime.now()}\n")
                f.write(error_message)
            
            # 가능하면 메시지 박스 표시
            try:
                app = QApplication.instance()
                if not app:
                    app = QApplication(sys.argv)
                msg_box = QMessageBox()
                msg_box.setIcon(QMessageBox.Icon.Critical)
                msg_box.setWindowTitle("오류 발생")
                msg_box.setText(f"애플리케이션 시작 중 오류가 발생했습니다.\n오류 로그가 {error_log_path}에 저장되었습니다.")
                msg_box.setDetailedText(error_message)
                msg_box.exec()
            except:
                pass
        except:
            pass
        
        return 1

if __name__ == "__main__":
    sys.exit(main()) 