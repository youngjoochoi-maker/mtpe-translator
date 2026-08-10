"""
novel_splitter
==============
번역용 소설(docx/txt)을 다양한 기준으로 자동 분권하고
각 분권의 분량을 계산하는 데스크톱 프로그램.

모듈 구성
- reader.py     : 파일 읽기(docx/txt, 인코딩 자동 감지)
- splitter.py   : 분권 로직(구분자/글자수/단어수 기준)
- counter.py    : 분량 계산(글자수/단어수/줄수)
- writer.py     : 분권 결과 저장
- processor.py  : 위 모듈들을 묶는 오케스트레이션
- mainwindow.py : PySide6 GUI
- utils.py      : 공통 유틸리티
- main.py       : 진입점
"""

__version__ = "1.0.0"
