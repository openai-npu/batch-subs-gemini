#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import logging
import threading
import queue
import time
from typing import Optional, Callable, List

# 싱글톤 로거 매니저
class LoggerManager:
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(LoggerManager, cls).__new__(cls)
                cls._instance._initialize()
            return cls._instance
    
    def _initialize(self):
        """싱글톤 인스턴스 초기화"""
        self.message_queue = queue.Queue()
        self.consumers = []
        self.is_running = True
        self.thread = threading.Thread(target=self._message_processor, daemon=True)
        self.thread.start()
    
    def register_consumer(self, consumer_func: Callable[[str], None]):
        """로그 메시지 소비자 등록"""
        if consumer_func not in self.consumers:
            self.consumers.append(consumer_func)
            return True
        return False
    
    def unregister_consumer(self, consumer_func: Callable[[str], None]):
        """로그 메시지 소비자 등록 해제"""
        if consumer_func in self.consumers:
            self.consumers.remove(consumer_func)
            return True
        return False
    
    def add_message(self, message: str):
        """메시지 큐에 추가"""
        self.message_queue.put(message)
    
    def _message_processor(self):
        """백그라운드 스레드에서 메시지 처리"""
        while self.is_running:
            try:
                # 메시지 큐에서 빼내기 (최대 0.1초 대기)
                try:
                    message = self.message_queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                
                # 등록된 모든 소비자에게 전달
                for consumer in list(self.consumers):  # 복사본으로 순회
                    try:
                        consumer(message)
                    except Exception as e:
                        print(f"Error in consumer: {e}")
                
                # 큐 작업 완료 표시
                self.message_queue.task_done()
            except Exception as e:
                print(f"Error in message processor: {e}")
    
    def shutdown(self):
        """로거 매니저 종료"""
        self.is_running = False
        if self.thread.is_alive():
            self.thread.join(timeout=1.0)


# 안전한 로그 핸들러
class SafeLogHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.manager = LoggerManager()
    
    def emit(self, record):
        try:
            msg = self.format(record)
            self.manager.add_message(msg)
        except Exception as e:
            print(f"Error in SafeLogHandler.emit: {e}")


# QT 로그 핸들러 (PyQt 시그널과 함께 사용)
class QtLogHandler(SafeLogHandler):
    def __init__(self, signal_func=None):
        super().__init__()
        if signal_func is not None:
            self.manager.register_consumer(signal_func)
    
    def connect_signal(self, signal_func):
        """시그널 연결"""
        return self.manager.register_consumer(signal_func)
    
    def disconnect_signal(self, signal_func):
        """시그널 연결 해제"""
        return self.manager.unregister_consumer(signal_func)


# 로깅 설정 함수
def setup_logging(log_level=logging.INFO, log_file=None):
    """애플리케이션 로깅 설정"""
    # 루트 로거 설정
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    
    # 기존 핸들러 모두 제거
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # 콘솔 핸들러 추가
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)
    
    # 파일 핸들러 추가 (옵션)
    if log_file:
        try:
            file_handler = logging.FileHandler(log_file, encoding='utf-8')
            file_handler.setLevel(log_level)
            file_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            file_handler.setFormatter(file_formatter)
            root_logger.addHandler(file_handler)
        except Exception as e:
            logging.error(f"Failed to set up file logging: {e}")
    
    return root_logger


# 간단한 테스트 코드
if __name__ == "__main__":
    # 로깅 설정
    logger = setup_logging(log_level=logging.DEBUG, log_file="test_log.log")
    
    # 테스트 소비자 함수
    def log_consumer(message):
        print(f"CONSUMER: {message}")
    
    # Qt 로그 핸들러 생성 및 연결
    qt_handler = QtLogHandler(log_consumer)
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