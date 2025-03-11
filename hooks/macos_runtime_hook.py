
# -*- coding: utf-8 -*-
# macOS용 PyInstaller 런타임 훅

import os
import sys
import logging

# 안전하게 Qt 백엔드 설정
try:
    if 'QT_QPA_PLATFORM' not in os.environ:
        os.environ['QT_QPA_PLATFORM'] = 'cocoa'
    
    # Python 경로 설정
    if getattr(sys, 'frozen', False):
        # PyInstaller로 번들된 앱의 경우
        app_path = os.path.dirname(sys.executable)
        
        # 필요한 경로 추가
        if not sys.path or app_path not in sys.path:
            sys.path.insert(0, app_path)
            os.environ['PYTHONPATH'] = app_path + os.pathsep + os.environ.get('PYTHONPATH', '')
        
        # 로깅 활성화
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            filename=os.path.expanduser('~/Documents/batch_subs_runtime.log'),
            filemode='w'
        )
        logging.info(f"macOS 런타임 훅 실행 중: {app_path}")
        logging.info(f"Python 경로: {sys.path}")
        logging.info(f"환경 변수: {[(k,v) for k,v in os.environ.items() if k.startswith(('QT_', 'PYTHON', 'PATH', 'DYLD_'))]}")
except Exception as e:
    # 표준 오류로도 출력
    print(f"런타임 훅 오류: {e}", file=sys.stderr)
    
    # 가능하면 파일에도 로깅
    try:
        with open(os.path.expanduser('~/Documents/batch_subs_hook_error.log'), 'w') as f:
            f.write(f"macOS 런타임 훅 오류: {e}")
    except:
        pass
