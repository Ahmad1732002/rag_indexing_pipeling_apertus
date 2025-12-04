"""
Given warc files create md and text files.
using: https://github.com/recrm/ArchiveTools#warc-extractorpy
"""
import subprocess
import os
import json
import re
import gzip
import pandas as pd
from bs4 import BeautifulSoup
from html_to_markdown import convert_to_markdown
from tqdm import tqdm

def warc_to_html(input_dir_path: str, output_dir_path: str):
    """
    Goes through the files in `input_dir_path`, finds all the warc (and warc.gz) files,
    extracts the html pages and saves them in the given `output_dir_path`.
    The hierarchy of directories is preserved for the html output.

    Args:
        input_dir_path (str): Path to the input directory.
        output_dir_path (str): Path to the output directory.
    """
    if not os.path.exists(output_dir_path):
        os.makedirs(output_dir_path)
    subprocess.call(f"python warc_extractor.py http:content-type:text/html -dump content -error -path {input_dir_path} -output_path {output_dir_path}", shell=True)

def warc_to_pdf(input_dir_path: str, output_dir_path: str):
    """
    Goes through the files in `input_dir_path`, finds all the warc (and warc.gz) files,
    extracts the pdf files and saves them in a `output_dir_path/wp-content` folder.

    Args:
        input_dir_path (str): Path to the input directory.
        output_dir_path (str): Path to the output directory.
    """
    if not os.path.exists(output_dir_path):
        os.makedirs(output_dir_path)
    subprocess.call(f"python warc_extractor.py http:content-type:pdf -dump content -error -path {input_dir_path} -output_path {output_dir_path}", shell=True)