"""Employee-facing text only; structured sources and attachment scope stay intact."""
import re

UUID=re.compile(r'\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b',re.I)
LABEL=r'(?:证据\s*(?:ID|编号|标识)?|evidence[_ ]?ids?|asset[_ ]?id|资料版本|适用版本|版本|演练标识)'
META_LINE=re.compile(r'^\s*(?:[-*•]\s*)?(?:\*\*)?'+LABEL+r'\s*(?:\*\*)?\s*[:：]',re.I)
META_PAREN=re.compile(r'[（(]\s*'+LABEL+r'\s*[:：][^）)\n]*[）)]',re.I)
OPEN_META=re.compile(r'[（(]\s*'+LABEL+r'\s*[:：][^）)\n]*$',re.I)
EVIDENCE=re.compile(r'(?:[—–；;·]\s*)?(?:\*\*)?(?:证据\s*(?:ID|编号|标识)?|evidence[_ ]?ids?|asset[_ ]?id)\s*(?:\*\*)?\s*[:：].*$',re.I)


def source_values(refs):
    return [value for ref in refs for value in [ref.get('version',''),*ref.get('evidence_ids',[])]
            if value and not value.isdecimal()]


def employee_text(text,*,final=True,internal_values=()):
    """Apply to cumulative streaming snapshots as well as final/cached answers."""
    for value in sorted(set(internal_values),key=len,reverse=True):
        text=re.sub(r'(?<![a-zA-Z0-9])'+re.escape(value)+r'(?![a-zA-Z0-9])','',text)
        if not final:
            # Values can be split at any token boundary, including the version.
            for n in range(min(len(value)-1,len(text)),0,-1):
                if text.endswith(value[:n]):
                    text=text[:-n];break
    output=[]
    for line in text.splitlines(keepends=True):
        if META_LINE.match(line):continue
        if re.search(r'https?://(?:127\.0\.0\.1|localhost):8060/api/v1/manuals/assets/',line):continue
        line=META_PAREN.sub('',line)
        line=OPEN_META.sub('',line)
        line=EVIDENCE.sub('',line)
        line=UUID.sub('',line)
        if not final:
            # A split metadata label must not briefly expose the following ID.
            line=re.sub(r'(?:[—–；;·]\s*)?(?:证据(?:\s*(?:I(?:D)?)?)?|evidence[_ ]?id)\s*[:：]?[^\n]*$', '',line,flags=re.I)
        if line.strip() in {'','-','*','•'}:
            if not line.strip():output.append('\n')
            continue
        output.append(line)
    result=''.join(output)
    return re.sub(r'\n{3,}','\n\n',result).strip()
