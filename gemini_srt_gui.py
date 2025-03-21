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
from PyQt6.QtCore import QThread, pyqtSignal, Qt, QSize, QMetaObject, Q_ARG, QObject
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

def extract_subtitle(video_file, output_srt, track_index=None, preferred_languages=None):
    """
    비디오 파일에서 자막을 추출하고 SRT 파일로 저장합니다.
    
    Args:
        video_file (str): 자막을 추출할 비디오 파일 경로
        output_srt (str): 출력 SRT 파일 경로
        track_index (int, optional): 추출할 자막 트랙 인덱스. None인 경우 자동 선택
        preferred_languages (list, optional): 선호하는 언어 코드 목록 (예: ['en', 'ko'])
    
    Returns:
        bool: 성공 여부
    """
    # 기본 선호 언어 설정
    if preferred_languages is None:
        preferred_languages = ['en', 'ko', 'und']
    
    try:
        # subtitle_utils 모듈을 사용할 수 있는 경우
        try:
            import subtitle_utils
            
            logger.info(f"subtitle_utils 모듈로 자막 추출 시도: {os.path.basename(video_file)}")
            # 트랙 인덱스가 주어진 경우 해당 트랙만 추출 시도
            if track_index is not None:
                success = subtitle_utils.extract_subtitle_auto(video_file, output_srt, 
                                                             track_index=track_index)
                if success:
                    logger.info(f"지정된 트랙 {track_index}에서 자막 추출 성공")
                    return True
                logger.warning(f"지정된 트랙 {track_index}에서 자막 추출 실패, 다른 방법 시도 중...")
            
            # 1. 자동 선택 방식으로 추출 시도
            success = subtitle_utils.extract_subtitle_auto(video_file, output_srt, 
                                                         preferred_languages=preferred_languages)
            if success:
                return True
                
            # 2. 단순 방식으로 추출 시도
            logger.info("자동 선택 방식 실패, 단순 방식 시도 중...")
            success = subtitle_utils.extract_subtitle_simple(video_file, output_srt)
            if success:
                return True
                
            # 3. 강제 추출 방식 시도
            logger.info("모든 일반 방식 실패, 강제 추출 시도 중...")
            success = subtitle_utils.extract_subtitle_force(video_file, output_srt)
            if success:
                return True
                
            logger.error(f"모든 자막 추출 방법이 실패했습니다: {os.path.basename(video_file)}")
            return False
            
        except ImportError:
            logger.warning("subtitle_utils 모듈을 찾을 수 없어 기본 추출 방식 사용")
    
        # subtitle_utils를 사용할 수 없는 경우 기본 방식으로 시도
        import ffmpeg_utils
        
        # ffmpeg 무결성 검사
        if not ffmpeg_utils.check_ffmpeg_integrity():
            logger.error("ffmpeg 무결성 검사에 실패했습니다.")
            return False
        
        # 기본 방식으로 자막 추출 시도
        cmd = [
            "ffmpeg", 
            "-y",
            "-i", video_file,
            "-map", "0:s:0" if track_index is None else f"0:s:{track_index}",
            "-c:s", "srt",
            output_srt
        ]
        
        logger.info(f"기본 ffmpeg로 자막 추출 시도: {os.path.basename(video_file)}")
        logger.debug(f"추출 명령어: {' '.join(cmd)}")
        
        # 새로운 ffmpeg_utils 함수 사용
        success, output = ffmpeg_utils.run_ffmpeg_command(cmd, timeout=120)
        
        # 출력 파일 확인
        if success and os.path.exists(output_srt) and os.path.getsize(output_srt) > 0:
            logger.info(f"기본 방식으로 자막 추출 성공: {os.path.basename(output_srt)}")
            return True
        else:
            logger.warning(f"자막 파일이 생성되지 않았거나 비어있습니다: {output_srt}")
            if not success:
                logger.warning(f"ffmpeg 오류: {output}")
            return False
            
    except Exception as e:
        logger.error(f"자막 추출 중 오류 발생: {type(e).__name__} - {e}")
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
            
            # 중요 UI 컴포넌트 초기화
            self.model_combo = None  # 모델 콤보박스 명시적 초기화
            
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
        
        # 모델 콤보 초기화 여부 확인 및 로깅
        print(f"init_ui에서 model_combo 초기화 전 상태: {self.model_combo}")
        logger.debug(f"init_ui에서 model_combo 초기화 전 상태: {self.model_combo}")
        
        # 이미 초기화되어 있으면 재사용, 아니면 새로 생성
        if self.model_combo is None:
            self.model_combo = QComboBox()
            logger.debug("init_ui에서 model_combo 새로 생성됨")
        
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
        # 디버깅 로그 추가
        logger.debug(f"start_translation 시작. model_combo 상태: {self.model_combo}")
        print(f"start_translation 시작. model_combo 상태: {self.model_combo}")
        
        api_key = self.api_input.text()
        input_folder = self.folder_input.text()
        
        # model_combo가 초기화되지 않았거나 없는 경우 체크
        if not hasattr(self, 'model_combo') or self.model_combo is None:
            logger.error("model_combo가 초기화되지 않았습니다")
            QMessageBox.critical(self, "오류", "모델 선택 컴포넌트를 초기화할 수 없습니다. 앱을 재시작하세요.")
            return
            
        model = self.model_combo.currentText() if self.model_combo.count() > 0 else ""

        if not api_key or not input_folder or not model:
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
            logger.info(f"언어 변경 중: 인덱스 {index}")
            
            # 언어 설정 변경
            if index == 0:
                self.current_language = 'en'
            else:
                self.current_language = 'ko'
                
            # UI 텍스트 업데이트 전 잠금 설정
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            QApplication.processEvents()  # UI 업데이트 처리
            
            try:
                # UI 텍스트 업데이트
                self.update_texts()
                logger.info(f"언어 변경 완료: {self.current_language}")
            except Exception as e:
                logger.error(f"언어 변경 중 오류: {str(e)}")
                QMessageBox.warning(self, 
                    "오류" if self.current_language == 'ko' else "Error", 
                    f"언어 변경 중 오류 발생: {str(e)}" if self.current_language == 'ko' else f"Error changing language: {str(e)}"
                )
            finally:
                # 언어 변경 후 잠금 해제
                QApplication.restoreOverrideCursor()
        except Exception as e:
            logger.error(f"언어 변경 처리 중 예외: {str(e)}")
            try:
                QApplication.restoreOverrideCursor()  # 예외 발생시에도 커서 복원
            except:
                pass

    def update_texts(self):
        try:
            logger.info(f"UI 텍스트 업데이트 중 (언어: {self.current_language})")
            
            # 사전에 없는 키에 대한 안전한 접근을 위한 helper 함수
            def safe_get_text(key, default=None):
                try:
                    result = TRANSLATIONS.get(self.current_language, {}).get(key)
                    if result is None and default is not None:
                        return default
                    return result or key
                except:
                    return default or key
            
            # 윈도우 타이틀 업데이트
            self.setWindowTitle(safe_get_text('title', 'Gemini SRT Translator'))
            
            # 각 UI 컴포넌트 텍스트 업데이트 (각 속성이 있는지 확인 후 업데이트)
            # 라벨 업데이트
            if hasattr(self, 'lang_label'):
                self.lang_label.setText(safe_get_text('language', '언어'))
                
            if hasattr(self, 'api_label'):
                self.api_label.setText(safe_get_text('api_key', 'API 키'))
                
            if hasattr(self, 'folder_label'):
                self.folder_label.setText(safe_get_text('input_folder', '입력 폴더'))
                
            if hasattr(self, 'model_label'):
                self.model_label.setText(safe_get_text('model', '모델'))
                
            if hasattr(self, 'progress_label'):
                self.progress_label.setText(safe_get_text('progress', '진행'))
                
            # 버튼 업데이트
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
            
            logger.info("UI 텍스트 업데이트 완료")
        except Exception as e:
            logger.error(f"텍스트 업데이트 중 오류: {str(e)}")
            # 기본 언어로 복원
            self.current_language = 'ko'
            raise  # 상위 함수가 처리할 수 있도록 예외 전파

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

    def setup_model_selection(self):
        """모델 선택 UI 구성"""
        try:
            logger.debug(f"setup_model_selection 시작. 현재 model_combo 상태: {self.model_combo}")
            print(f"setup_model_selection 시작. 현재 model_combo 상태: {self.model_combo}")
            
            # 모델 선택 레이아웃
            model_layout = QHBoxLayout()
            model_label = QLabel(TRANSLATIONS[self.current_language]['model'])
            
            # 이미 초기화되어 있는지 확인
            if self.model_combo is None:
                logger.debug("setup_model_selection에서 model_combo 초기화")
                self.model_combo = QComboBox()
            else:
                logger.debug("setup_model_selection에서 기존 model_combo 재사용")
            
            self.get_models_btn = QPushButton(TRANSLATIONS[self.current_language]['get_models'])
            self.get_models_btn.clicked.connect(self.fetch_models)
            model_layout.addWidget(model_label)
            model_layout.addWidget(self.model_combo)
            model_layout.addWidget(self.get_models_btn)
            
            # 메인 UI에 추가 (tab1_layout이 있으면 거기에 추가)
            if hasattr(self, 'tab1_layout') and self.tab1_layout:
                self.tab1_layout.addLayout(model_layout)
            else:
                # 중앙 위젯의 레이아웃에 직접 추가
                central_widget = self.centralWidget()
                if central_widget and central_widget.layout():
                    central_widget.layout().addLayout(model_layout)
                else:
                    logger.error("중앙 위젯 또는 레이아웃이 없습니다")
            
            logger.info("모델 선택 UI 설정 완료")
        except Exception as e:
            logger.error(f"모델 선택 UI 설정 중 오류: {str(e)}")

    def fetch_models(self):
        try:
            logger.debug(f"fetch_models 시작. model_combo 상태: {self.model_combo}")
            print(f"fetch_models 시작. model_combo 상태: {self.model_combo}")
            
            if not hasattr(self, 'model_combo') or self.model_combo is None:
                logger.error("model_combo가 초기화되지 않았습니다.")
                # 모델 선택 UI 재설정 시도
                logger.debug("setup_model_selection 호출 시도")
                self.setup_model_selection()
                logger.debug(f"setup_model_selection 호출 후 model_combo 상태: {self.model_combo}")
                
                if not hasattr(self, 'model_combo') or self.model_combo is None:
                    QMessageBox.critical(self, "오류", "모델 선택 컴포넌트를 초기화할 수 없습니다.")
                    return

            # API 키 가져오기
            api_key = self.api_input.text()
            if not api_key:
                if hasattr(self, 'status_label') and self.status_label:
                    self.status_label.setText(self.get_translation('error_api_key', 'API 키가 필요합니다'))
                if hasattr(self, 'log_text') and self.log_text:
                    self.log_text.append(self.get_translation('error_api_key', 'API 키가 필요합니다'))
                QMessageBox.warning(self, self.get_translation('error', '오류'), 
                                   self.get_translation('error_api_key', 'API 키가 필요합니다'))
                return

            # 모델 목록 가져오기 시작
            self.get_models_btn.setEnabled(False)
            if hasattr(self, 'status_label') and self.status_label:
                self.status_label.setText(self.get_translation('loading_models', '모델 목록 불러오는 중...'))
            if hasattr(self, 'log_text') and self.log_text:
                self.log_text.append(self.get_translation('loading_models', '모델 목록 불러오는 중...'))

            # 워커 스레드 시작
            worker = ModelLoaderWorker(api_key)
            worker.models_loaded.connect(self.on_models_loaded)
            worker.error.connect(self.on_model_load_error)
            self.worker_thread = QThread()
            worker.moveToThread(self.worker_thread)
            self.worker_thread.started.connect(worker.load_models)
            self.worker_thread.start()
        except Exception as e:
            logger.error(f"모델 목록 조회 중 오류: {str(e)}")
            if hasattr(self, 'get_models_btn') and self.get_models_btn:
                self.get_models_btn.setEnabled(True)
            if hasattr(self, 'status_label') and self.status_label:
                self.status_label.setText(f"오류: {str(e)}")
            if hasattr(self, 'log_text') and self.log_text:
                self.log_text.append(f"오류: {str(e)}")
            QMessageBox.critical(self, "오류", f"모델 목록 조회 중 오류 발생: {str(e)}")

    def on_models_loaded(self, models):
        try:
            logger.debug(f"on_models_loaded 시작. model_combo 상태: {self.model_combo}")
            print(f"on_models_loaded 시작. model_combo 상태: {self.model_combo}")
            
            if not hasattr(self, 'model_combo') or self.model_combo is None:
                logger.error("model_combo가 초기화되지 않았습니다")
                # 모델 선택 UI 다시 생성 시도
                logger.debug("setup_model_selection 호출 시도")
                self.setup_model_selection()
                logger.debug(f"setup_model_selection 호출 후 model_combo 상태: {self.model_combo}")
                
                if not hasattr(self, 'model_combo') or self.model_combo is None:
                    QMessageBox.critical(self, "오류", "모델 선택 컴포넌트를 초기화할 수 없습니다")
                    return
                
            # 모델 목록이 비어있는 경우 처리
            if not models:
                logger.warning("가져온 모델 목록이 비어있습니다")
                if hasattr(self, 'status_label') and self.status_label:
                    self.status_label.setText(self.get_translation('no_models', '가져온 모델이 없습니다'))
                if hasattr(self, 'log_text') and self.log_text:
                    self.log_text.append(self.get_translation('no_models', '가져온 모델이 없습니다'))
                if hasattr(self, 'get_models_btn') and self.get_models_btn:
                    self.get_models_btn.setEnabled(True)
                return
                
            # 모델 목록 업데이트
            self.model_combo.clear()
            self.model_combo.addItems(models)
            
            # 상태 업데이트
            if hasattr(self, 'status_label') and self.status_label:
                self.status_label.setText(self.get_translation('models_loaded', '모델 목록 로드 완료'))
            
            # 버튼 다시 활성화
            if hasattr(self, 'get_models_btn') and self.get_models_btn:
                self.get_models_btn.setEnabled(True)
            
            # 로그에 기록
            if hasattr(self, 'log_text') and self.log_text:
                self.log_text.append(self.get_translation('models_loaded', '모델 목록 로드 완료'))
                
            logger.info(f"모델 {len(models)}개 로드 완료")
            
            # 스레드 정리
            if hasattr(self, 'worker_thread') and self.worker_thread and self.worker_thread.isRunning():
                self.worker_thread.quit()
                self.worker_thread.wait()
                
        except Exception as e:
            logger.error(f"모델 목록 처리 중 오류: {str(e)}")
            if hasattr(self, 'get_models_btn') and self.get_models_btn:
                self.get_models_btn.setEnabled(True)
            if hasattr(self, 'log_text') and self.log_text:
                self.log_text.append(f"오류: {str(e)}")
            QMessageBox.critical(self, "오류", f"모델 목록 처리 중 오류 발생: {str(e)}")
    
    def on_model_load_error(self, error_msg):
        try:
            logger.error(f"모델 로드 오류: {error_msg}")
            
            # 상태 업데이트
            if hasattr(self, 'status_label') and self.status_label:
                self.status_label.setText(f"{self.get_translation('error', '오류')}: {error_msg}")
            
            # 로그에 기록
            if hasattr(self, 'log_text') and self.log_text:
                self.log_text.append(f"{self.get_translation('error', '오류')}: {error_msg}")
            
            # 버튼 다시 활성화
            if hasattr(self, 'get_models_btn') and self.get_models_btn:
                self.get_models_btn.setEnabled(True)
                
            # 오류 표시
            QMessageBox.critical(self, 
                self.get_translation('error', '오류'), 
                f"{self.get_translation('error_loading_models', '모델 목록 로드 중 오류 발생')}: {error_msg}"
            )
            
            # 스레드 정리
            if hasattr(self, 'worker_thread') and self.worker_thread and self.worker_thread.isRunning():
                self.worker_thread.quit()
                self.worker_thread.wait()
                
        except Exception as e:
            logger.error(f"모델 로드 오류 처리 중 예외 발생: {str(e)}")
            # 기본 오류 메시지라도 보여주기
            QMessageBox.critical(self, "오류", f"모델 로드 실패: {error_msg}")

class ModelLoaderWorker(QObject):
    models_loaded = pyqtSignal(list)
    error = pyqtSignal(str)
    
    def __init__(self, api_key):
        super().__init__()
        self.api_key = api_key
        
    def load_models(self):
        try:
            models = []
            # 모델 목록 획득 
            if self.api_key:
                from google.generativeai import configure, list_models
                configure(api_key=self.api_key)
                available_models = list_models()
                
                # 이름 추출
                for model in available_models:
                    if hasattr(model, 'name'):
                        name = model.name
                        # 마지막 슬래시 이후 부분만 사용
                        if '/' in name:
                            name = name.split('/')[-1]
                        models.append(name)
            
            # 결과 반환
            self.models_loaded.emit(models)
        except Exception as e:
            logger.error(f"모델 목록 가져오기 오류: {str(e)}")
            self.error.emit(str(e))

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