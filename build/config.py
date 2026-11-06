"""Paths and credits for building Lamphouse and Answer Print. Override paths with environment variables if needed."""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

# Who modified the spektrafilm data (required by the CC BY-SA 4.0 attribution)
AUTHOR = 'Nico Welgemoed'
PROJECT_URL = 'https://github.com/Nicowelgemoed/lamphouse'
VERSION = '1.2.0'

# spektrafilm checkout (film data): https://github.com/andreavolpato/spektrafilm
SPEKTRAFILM_DIR = os.environ.get('SPEKTRAFILM_DIR', os.path.join(HERE, 'third_party', 'spektrafilm'))
SPEKTRAFILM_DATA = os.path.join(SPEKTRAFILM_DIR, 'src', 'spektrafilm', 'data') + os.sep

TEMPLATES = os.path.join(HERE, 'templates')
OUT_DIR = os.path.join(REPO, 'dctl')
OUT_STANDALONE = os.path.join(OUT_DIR, 'AnswerPrint.dctl')
OUT_LAMPHOUSE = os.path.join(OUT_DIR, 'Lamphouse.dctl')
