# normalizer.py
import re

DEPARTMENTS = ["abcd", "efgh"]
EMPLOYEE_NAMES = ["sarang deshpande", "pqrs"]

DEPARTMENTS.sort(key=len, reverse=True)
EMPLOYEE_NAMES.sort(key=len, reverse=True)


def replace_phrases(text, phrase_list, placeholder):
    for phrase in phrase_list:
        pattern = r'\b' + re.escape(phrase) + r'\b'
        text = re.sub(pattern, placeholder, text)
    return text


def normalize_question(q):
    q = q.lower()

    q = re.sub(r'\btr\d+\b', '<EMP_ID>', q)
    q = re.sub(r'\b\d+\b', '<NUMBER>', q)

    q = replace_phrases(q, DEPARTMENTS, '<DEPARTMENT>')
    q = replace_phrases(q, EMPLOYEE_NAMES, '<EMP_NAME>')

    return q
