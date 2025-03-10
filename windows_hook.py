import os
import sys
import ctypes
from pathlib import Path

# DLL 로딩 에러 방지를 위한 준비 작업을 수행합니다.

# 1. 실행 경로를 PATH에 추가
if hasattr(sys, 'frozen'):
    bundle_dir = getattr(sys, '_MEIPASS', os.path.abspath(os.path.dirname(sys.executable)))
    os.environ['PATH'] = f"{bundle_dir}{os.pathsep}{os.environ.get('PATH', '')}"
    
    # PyInstaller가 생성한 _internal 디렉토리 추가
    internal_dir = os.path.join(os.path.dirname(sys.executable), '_internal')
    if os.path.exists(internal_dir):
        os.environ['PATH'] = f"{internal_dir}{os.pathsep}{os.environ['PATH']}"

    # 2. bin 디렉토리가 있으면 PATH에 추가
    bin_dir = os.path.join(bundle_dir, 'bin')
    if os.path.exists(bin_dir):
        os.environ['PATH'] = f"{bin_dir}{os.pathsep}{os.environ['PATH']}"

# 3. 인코딩 설정
if hasattr(sys, 'frozen'):
    # UTF-8 사용 설정
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer)
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer)

# 4. DLL 로딩 문제 감지 및 처리
def fix_dll_search():
    try:
        # 애플리케이션 디렉토리를 DLL 검색 경로에 추가
        if hasattr(sys, 'frozen'):
            base_dir = os.path.dirname(sys.executable)
            # SetDllDirectoryW 함수 호출 (Windows API)
            try:
                ctypes.windll.kernel32.SetDllDirectoryW(base_dir)
            except Exception:
                pass
            
            # Python DLL 경로를 현재 디렉토리로 변경 시도
            try:
                executable_dir = os.path.dirname(sys.executable)
                os.chdir(executable_dir)
                
                # DLL 파일 존재 확인
                dll_path = os.path.join(executable_dir, 'python311.dll')
                if os.path.exists(dll_path):
                    print(f"Python DLL found at: {dll_path}")
                else:
                    print(f"Python DLL not found at: {dll_path}")
                    
                    # _internal 디렉토리 확인
                    internal_path = os.path.join(executable_dir, '_internal', 'python311.dll')
                    if os.path.exists(internal_path):
                        print(f"Python DLL found in _internal: {internal_path}")
            except Exception as e:
                print(f"Error changing directory: {e}")
    except Exception as e:
        print(f"Error in fix_dll_search: {e}")

fix_dll_search()

# 디버그 정보 출력
if hasattr(sys, 'frozen'):
    print(f"Python executable: {sys.executable}")
    print(f"Current directory: {os.getcwd()}")
    print(f"PATH environment: {os.environ['PATH']}")
    print(f"sys._MEIPASS: {getattr(sys, '_MEIPASS', 'Not available')}")
    
    # DLL 위치 확인
    for path in os.environ['PATH'].split(os.pathsep):
        dll_file = os.path.join(path, "python311.dll")
        if os.path.exists(dll_file):
            print(f"Found python311.dll at: {dll_file}") 