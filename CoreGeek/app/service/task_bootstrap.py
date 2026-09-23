"""Build a bounded, read-only command for the official sandbox; never run it here."""
import re
import shlex


# Paths come from the current task only; no replay filenames or answers are used.
PATH_PATTERN = re.compile(r'(?<![\w./])(/[A-Za-z0-9_./-]+\.md)(?![\w.])')
READ_SCRIPT = r'''from pathlib import Path
import json,sys
p=Path(sys.argv[1])
def read_text(path, limit):
    with path.open(encoding='utf-8', errors='replace') as f:
        text=f.read(limit+1)
    return {'path':str(path),'text':text[:limit],'truncated':len(text)>limit}
result={'task_file':str(p)}
try:
    result['task']=read_text(p,7000)
    docs=[]
    names=[]
    for q in sorted(p.parent.iterdir()):
        if len(names)>=40:break
        if q.is_symlink():continue
        names.append(q.name)
        if q!=p and q.suffix=='.md' and any(k in q.name.lower() for k in ('api','sdk','interface','readme')) and len(docs)<2:
            docs.append(read_text(q,1500))
    result.update(interface_docs=docs,nearby_files=names)
except (OSError,ValueError) as e:
    result['read_error']=str(e)[:400]
print(json.dumps(result,ensure_ascii=False))
'''


def bootstrap_command(task: str) -> str:
    """Only bootstrap an unambiguous explicit absolute Markdown task path."""
    paths = set(PATH_PATTERN.findall(task))
    if len(paths) != 1:
        return ''
    path = next(iter(paths))
    if '..' in path.split('/') or len(path) > 512:
        return ''
    return 'python3 -c ' + shlex.quote(READ_SCRIPT) + ' ' + shlex.quote(path)
