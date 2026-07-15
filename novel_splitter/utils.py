"""
utils.py
--------
프로그램 전반에서 공통으로 사용하는 유틸리티 함수 모음.

- 파일 형식 판별
- 출력 파일명 생성 (4자리 번호, 앞/뒤 번호 옵션)
- 안전한 파일 시스템 경로 처리
"""

from __future__ import annotations

import os
import re

# 지원하는 파일 확장자
SUPPORTED_EXTENSIONS = (".docx", ".txt")


def get_file_extension(path: str) -> str:
    """파일 경로에서 소문자 확장자를 반환한다. 예) '.docx'"""
    return os.path.splitext(path)[1].lower()


def is_supported_file(path: str) -> bool:
    """지원하는 파일(docx, txt)인지 여부를 반환한다."""
    return get_file_extension(path) in SUPPORTED_EXTENSIONS


def get_stem(path: str) -> str:
    """확장자를 제외한 파일 이름(stem)을 반환한다. 예) '/a/소설.docx' -> '소설'"""
    return os.path.splitext(os.path.basename(path))[0]


def sanitize_filename(name: str) -> str:
    """
    파일명으로 사용할 수 없는 문자를 '_'로 치환한다.
    Windows / macOS 양쪽에서 안전한 이름을 만들기 위함.
    """
    # Windows에서 금지되는 문자: \ / : * ? " < > |
    cleaned = re.sub(r'[\\/:*?"<>|]', "_", name)
    # 앞뒤 공백/마침표 제거 (Windows는 마침표로 끝나는 이름을 허용하지 않음)
    cleaned = cleaned.strip().strip(".")
    return cleaned or "output"


def build_output_filename(
    stem: str,
    index: int,
    extension: str,
    number_position: str = "suffix",
    digits: int = 4,
) -> str:
    """
    출력 파일명을 생성한다.

    Parameters
    ----------
    stem : 원본 파일의 기본 이름 (예: '소설')
    index : 분권 번호 (1부터 시작)
    extension : 확장자 (예: '.docx')
    number_position : 'suffix'(뒤, 기본값) 또는 'prefix'(앞)
    digits : 번호 자릿수 (기본 4 -> 0001)

    Returns
    -------
    예) build_output_filename('소설', 1, '.docx') -> '소설_0001.docx'
        build_output_filename('소설', 1, '.docx', 'prefix') -> '0001_소설.docx'
    """
    number = str(index).zfill(digits)
    stem = sanitize_filename(stem)

    if number_position == "prefix":
        name = f"{number}_{stem}"
    else:  # 기본값: 뒤에 번호
        name = f"{stem}_{number}"

    return f"{name}{extension}"


def ensure_dir(path: str) -> str:
    """디렉터리가 없으면 생성하고, 경로를 그대로 반환한다."""
    os.makedirs(path, exist_ok=True)
    return path


def unique_dir(path: str) -> str:
    """
    이미 존재하는 디렉터리와 충돌하지 않는 경로를 반환한다.
    예) '소설'이 있으면 '소설_2', '소설_3' ... 를 시도.
    (덮어쓰기를 원치 않을 때 출력 폴더 충돌 회피용)
    """
    if not os.path.exists(path):
        return path
    counter = 2
    while True:
        candidate = f"{path}_{counter}"
        if not os.path.exists(candidate):
            return candidate
        counter += 1
