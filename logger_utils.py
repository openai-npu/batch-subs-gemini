#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import logging
import threading
import queue
import time
import re
from typing import Callable, List, Optional
from datetime import datetime
from PyQt6.QtCore import QObject, pyqtSignal, QMetaObject, Qt, Q_ARG, QTimer

# 싱글톤 로거 매니저
class LoggerManager:
    _instance = None
    _lock = threading.Lock()
    
    @classmethod
    def instance(cls):
        """싱글톤 인스턴스 반환"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance
    
    def __init__(self):
        """로거 매니저 초기화"""
        self._consumers = []
        self._message_queue = queue.Queue()
        self._shutdown_flag = threading.Event()
        self._processor_thread = None
        self._max_queue_size = 1000  # 최대 큐 크기
        self._last_update_time = 0
        self._update_interval = 0.1  # 업데이트 간격 (초)
        self._batch_size = 10  # 한 번에 처리할 최대 메시지 수
        self._is_running = False
        self._filter_pattern = re.compile(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]')  # 제어 문자 필터
    
    def start(self):
        """메시지 처리 스레드 시작"""
        if not self._is_running:
            self._is_running = True
            self._shutdown_flag.clear()
            self._processor_thread = threading.Thread(
                target=self._message_processor,
                name="LoggerThread",
                daemon=True
            )
            self._processor_thread.start()
    
    def register_consumer(self, consumer_func: Callable[[str], None]):
        """로그 소비자 등록"""
        if consumer_func not in self._consumers:
            self._consumers.append(consumer_func)
            
        # 처리 스레드가 실행 중이 아니면 시작
        if not self._is_running:
            self.start()
    
    def unregister_consumer(self, consumer_func: Callable[[str], None]):
        """로그 소비자 제거"""
        if consumer_func in self._consumers:
            self._consumers.remove(consumer_func)
    
    def add_message(self, message: str):
        """로그 메시지 추가"""
        # 큐가 너무 크면 오래된 메시지 버림
        if self._message_queue.qsize() >= self._max_queue_size:
            try:
                self._message_queue.get_nowait()  # 가장 오래된 메시지 제거
            except queue.Empty:
                pass
        
        # 안전한 메시지 필터링 적용
        try:
            # 제어 문자 필터링
            safe_message = self._filter_pattern.sub('', message)
            # 빈 메시지는 무시
            if safe_message:
                self._message_queue.put(safe_message)
        except Exception:
            # 메시지 처리 중 오류 발생 시 안전한 대체 메시지 사용
            self._message_queue.put("[로그 메시지 처리 오류]")
    
    def _message_processor(self):
        """로그 메시지 처리 스레드"""
        while not self._shutdown_flag.is_set():
            try:
                # 메시지 배치 처리
                current_time = time.time()
                messages = []
                
                # 일정 간격으로만 UI 업데이트
                if current_time - self._last_update_time >= self._update_interval:
                    # 최대 배치 크기만큼 메시지 수집
                    for _ in range(self._batch_size):
                        try:
                            message = self._message_queue.get_nowait()
                            messages.append(message)
                            self._message_queue.task_done()
                        except queue.Empty:
                            break
                    
                    # 수집된 메시지가 있으면 모든 소비자에게 전달
                    if messages:
                        # 메시지 배치를 하나의 문자열로 결합
                        batch_message = "\n".join(messages)
                        
                        for consumer in list(self._consumers):  # 복사본으로 반복
                            try:
                                consumer(batch_message)
                            except Exception:
                                # 소비자가 오류를 발생시키면 제거 고려
                                pass
                                
                        self._last_update_time = current_time
                
                # 잠시 대기 (CPU 사용량 감소)
                time.sleep(0.01)
                
            except Exception:
                # 처리 중 예외 발생 시에도 스레드는 계속 실행
                time.sleep(0.1)
        
        # 종료 전 나머지 메시지 처리
        self._flush_remaining_messages()
    
    def _flush_remaining_messages(self):
        """남은 메시지 모두 처리"""
        try:
            remaining_messages = []
            while not self._message_queue.empty():
                try:
                    message = self._message_queue.get_nowait()
                    remaining_messages.append(message)
                    self._message_queue.task_done()
                except queue.Empty:
                    break
            
            if remaining_messages and self._consumers:
                batch_message = "\n".join(remaining_messages)
                for consumer in list(self._consumers):
                    try:
                        consumer(batch_message)
                    except Exception:
                        pass
        except Exception:
            pass
    
    def shutdown(self):
        """로깅 시스템 종료"""
        if self._is_running:
            self._shutdown_flag.set()
            if self._processor_thread and self._processor_thread.is_alive():
                self._processor_thread.join(timeout=1.0)
            self._is_running = False


# Qt 시그널을 사용하는 로그 핸들러
class QtLogSignaler(QObject):
    """Qt 시그널을 발생시키는 로그 시그널러"""
    log_signal = pyqtSignal(str)
    
    def __init__(self):
        super().__init__()


# 로그 핸들러 기본 클래스
class SafeLogHandler(logging.Handler):
    """스레드 안전한 로그 핸들러"""
    def __init__(self):
        super().__init__()
        self.manager = LoggerManager.instance()
        
    def emit(self, record):
        """로그 레코드 처리"""
        try:
            message = self.format(record)
            self.manager.add_message(message)
        except Exception:
            # 로그 처리 중 오류가 발생해도 애플리케이션은 계속 실행
            pass


# Qt 앱용 로그 핸들러
class QtLogHandler(SafeLogHandler):
    """Qt GUI 로깅용 핸들러"""
    def __init__(self):
        super().__init__()
        self.signaler = QtLogSignaler()
        self._max_text_length = 100000  # 최대 로그 길이
        
    def connect_signal(self, slot_function):
        """시그널과 슬롯 연결"""
        try:
            self.signaler.log_signal.connect(slot_function, Qt.ConnectionType.QueuedConnection)
            
            # 로그 소비자로 안전한 시그널 방출 함수 등록
            self.manager.register_consumer(self._emit_signal_safely)
        except Exception:
            pass
    
    def disconnect_signal(self, slot_function):
        """시그널과 슬롯 연결 해제"""
        try:
            self.signaler.log_signal.disconnect(slot_function)
            self.manager.unregister_consumer(self._emit_signal_safely)
        except Exception:
            pass
    
    def _emit_signal_safely(self, message):
        """안전하게 시그널 방출 (메인 스레드로 전달)"""
        try:
            # 메인 스레드에서 시그널 방출
            QMetaObject.invokeMethod(
                self.signaler, 
                "log_signal.emit", 
                Qt.ConnectionType.QueuedConnection,
                Q_ARG(str, message)
            )
        except Exception:
            pass


# 파일 로그 핸들러 (로그 파일 자동 회전)
class RotatingFileHandler(SafeLogHandler):
    """파일에 로그를 기록하는 핸들러 (자동 회전)"""
    def __init__(self, filename, max_size_mb=5, backup_count=3):
        super().__init__()
        self.filename = filename
        self.max_size_bytes = max_size_mb * 1024 * 1024
        self.backup_count = backup_count
        self._file = None
        self._current_size = 0
        self._open_log_file()
        
        # 파일 기록용 소비자 등록
        self.manager.register_consumer(self._write_to_file)
    
    def _open_log_file(self):
        """로그 파일 열기"""
        try:
            # 파일 크기 확인
            if os.path.exists(self.filename):
                self._current_size = os.path.getsize(self.filename)
                
                # 최대 크기 초과 시 회전
                if self._current_size >= self.max_size_bytes:
                    self._rotate_log()
            
            # 파일 열기 (추가 모드)
            self._file = open(self.filename, 'a', encoding='utf-8')
        except Exception:
            self._file = None
    
    def _rotate_log(self):
        """로그 파일 회전"""
        try:
            # 기존 백업 파일 처리
            for i in range(self.backup_count - 1, 0, -1):
                src = f"{self.filename}.{i}"
                dst = f"{self.filename}.{i+1}"
                
                if os.path.exists(src):
                    if os.path.exists(dst):
                        os.remove(dst)
                    os.rename(src, dst)
            
            # 현재 로그 파일을 첫 번째 백업으로 이동
            if os.path.exists(self.filename):
                backup = f"{self.filename}.1"
                if os.path.exists(backup):
                    os.remove(backup)
                os.rename(self.filename, backup)
        except Exception:
            pass
    
    def _write_to_file(self, message):
        """파일에 로그 메시지 기록"""
        if not self._file:
            try:
                self._open_log_file()
            except Exception:
                return
        
        try:
            # 타임스탬프 추가
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            full_message = f"[{timestamp}] {message}\n"
            
            # 파일에 기록
            self._file.write(full_message)
            self._file.flush()
            
            # 파일 크기 갱신
            self._current_size += len(full_message.encode('utf-8'))
            
            # 최대 크기 초과 시 회전
            if self._current_size >= self.max_size_bytes:
                self._file.close()
                self._rotate_log()
                self._open_log_file()
                self._current_size = 0
        except Exception:
            # 파일 기록 실패 시 파일 다시 열기 시도
            try:
                if self._file:
                    self._file.close()
                self._file = None
                self._open_log_file()
            except Exception:
                pass
    
    def close(self):
        """핸들러 종료"""
        try:
            self.manager.unregister_consumer(self._write_to_file)
            if self._file:
                self._file.close()
                self._file = None
        except Exception:
            pass


# 콘솔 로그 핸들러
class SafeConsoleHandler(SafeLogHandler):
    """안전한 콘솔 로그 핸들러"""
    def __init__(self):
        super().__init__()
        self.manager.register_consumer(self._write_to_console)
    
    def _write_to_console(self, message):
        """콘솔에 로그 메시지 출력"""
        try:
            print(message, file=sys.stdout)
            sys.stdout.flush()
        except Exception:
            pass
    
    def close(self):
        """핸들러 종료"""
        try:
            self.manager.unregister_consumer(self._write_to_console)
        except Exception:
            pass


# 로깅 설정
def setup_logging(name="app", log_level=logging.INFO, log_file=None, console=True):
    """애플리케이션 로깅 설정"""
    try:
        # 기본 로거 설정
        logger = logging.getLogger(name)
        logger.setLevel(log_level)
        
        # 기존 핸들러 제거
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
        
        # 포맷터 생성
        formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        # 로그 매니저 시작
        LoggerManager.instance().start()
        
        # 콘솔 핸들러 추가
        if console:
            console_handler = SafeConsoleHandler()
            console_handler.setLevel(log_level)
            console_handler.setFormatter(formatter)
            logger.addHandler(console_handler)
        
        # 파일 핸들러 추가
        if log_file:
            file_handler = RotatingFileHandler(log_file)
            file_handler.setLevel(log_level)
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
        
        return logger
        
    except Exception as e:
        # 로깅 설정 중 오류 발생 시 기본 로거 반환
        fallback_logger = logging.getLogger(name)
        fallback_logger.setLevel(log_level)
        
        # 기존 핸들러가 없으면 스트림 핸들러 추가
        if not fallback_logger.handlers:
            handler = logging.StreamHandler()
            handler.setLevel(log_level)
            formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            fallback_logger.addHandler(handler)
            
            # 로깅 설정 실패 경고
            fallback_logger.warning(f"로깅 시스템 초기화 실패: {e}")
        
        return fallback_logger


# 앱 종료 시 로깅 시스템 정리
def shutdown_logging():
    """로깅 시스템 종료 및 정리"""
    try:
        LoggerManager.instance().shutdown()
    except Exception:
        pass


# 간단한 테스트 코드
if __name__ == "__main__":
    # 로깅 설정
    logger = setup_logging(log_level=logging.DEBUG, log_file="test_log.log")
    
    # 테스트 소비자 함수
    def log_consumer(message):
        print(f"CONSUMER: {message}")
    
    # Qt 로그 핸들러 생성 및 연결
    qt_handler = QtLogHandler()
    qt_handler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
    logger.addHandler(qt_handler)
    
    # 테스트 로그 메시지
    logger.debug("This is a debug message")
    logger.info("This is an info message")
    logger.warning("This is a warning message")
    logger.error("This is an error message")
    
    # 소비자 연결 해제
    qt_handler.disconnect_signal(log_consumer)
    
    # 추가 로그 (이제 소비자에게 전달되지 않음)
    logger.info("This won't go to the consumer")
    
    # 잠시 대기하여 모든 메시지가 처리되게 함
    time.sleep(0.5) 