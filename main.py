#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import contextlib
import io
import os
import glob
import logging
import subprocess
import gemini_srt_translator as gst

# 로깅 설정 (시간, 레벨, 메시지)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt='%Y-%m-%d %H:%M:%S'
)

def extract_subtitle(mkv_file, output_srt):
    """
    ffmpeg를 이용하여 MKV 파일에서 첫 번째 자막 트랙을 추출합니다.
    (언어 필터 대신 첫 번째 트랙(0:s:0)을 선택합니다.)
    성공하면 True, 실패하면 False를 반환합니다.
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
    gemini_srt_translator 모듈을 사용하여 추출된 SRT 파일을 target_language로 번역합니다.
    번역된 결과는 원본 파일명에 '_translated' 접미사를 붙인 파일로 저장됩니다.
    """
    base, ext = os.path.splitext(srt_file)
    output_file = f"{base}_translated{ext}"
    # gemini_srt_translator 설정
    gst.input_file = srt_file
    gst.output_file = output_file
    logging.info(f"[번역 시작] {os.path.basename(srt_file)} -> {os.path.basename(output_file)}")
    try:
        gst.translate()
        logging.info(f"[번역 완료] {os.path.basename(output_file)} 생성됨")
    except Exception as ex:
        logging.error(f"[번역 에러] {os.path.basename(srt_file)} 처리 중 에러 발생: {ex}")

def get_models():
    """
    gst.listmodels()의 출력을 캡처하여 모델 목록을 문자열 리스트로 반환합니다.
    (모듈 내 listmodels()는 사용 가능한 모델들을 콘솔에 출력합니다.)
    """
    capture_output = io.StringIO()
    with contextlib.redirect_stdout(capture_output):
        gst.listmodels()
    output = capture_output.getvalue()
    # 빈 줄 제거하고, 각 줄의 텍스트를 모델로 간주합니다.
    models = [line.strip() for line in output.splitlines() if line.strip()]
    return models

def main():
    # Gemini API Key와 대상 언어 설정
    gst.gemini_api_key  = ""
    gst.gemini_api_key2 = ""
    gst.target_language = "Korean"

    # 사용할 모델 목록 (예시)
    models = get_models()
    print("========= 사용 가능한 모델 =========")
    for i, model in enumerate(models, start=1):
        print(f"{i}. {model}")
    user_choice = input("사용할 모델의 번호를 입력하세요 (예: 1): ").strip()
    try:
        choice_num = int(user_choice)
        if 1 <= choice_num <= len(models):
            gst.model_name = models[choice_num - 1]
            logging.info(f"선택된 모델: {gst.model_name}")
        else:
            logging.warning("잘못된 번호 입력, 기본 모델 사용")
            gst.model_name = models[0]
    except ValueError:
        logging.warning("숫자가 아닌 입력, 기본 모델 사용")
        gst.model_name = models[0]

    # MKV 파일들이 위치한 폴더 경로 지정 (절대 경로 처리)
    input_folder = ""
    input_folder = os.path.abspath(input_folder)

    # 특수문자 처리: glob.escape() 사용
    escaped_folder = glob.escape(input_folder)
    mkv_pattern = os.path.join(escaped_folder, "*.mkv")
    logging.info(f"검색 패턴: {mkv_pattern}")

    mkv_files = sorted(glob.glob(mkv_pattern))
    total_files = len(mkv_files)

    if total_files == 0:
        logging.warning(f"지정한 폴더에 MKV 파일이 없습니다: {input_folder}")
        return

    logging.info(f"총 {total_files}개의 MKV 파일 처리 시작")

    for index, mkv_file in enumerate(mkv_files, start=1):
        logging.info(f"파일 [{index}/{total_files}]: {os.path.basename(mkv_file)} 처리 시작")

        base_name, _ = os.path.splitext(mkv_file)
        srt_file = f"{base_name}_eng.srt"

        # 자막 추출에 성공하면 번역 진행, 실패 시 해당 파일 건너뜀
        if extract_subtitle(mkv_file, srt_file):
            translate_subtitle(srt_file)
        else:
            logging.error(f"파일 건너뜀: {os.path.basename(mkv_file)}")

    logging.info("모든 파일 처리 완료")

if __name__ == "__main__":
    main()
