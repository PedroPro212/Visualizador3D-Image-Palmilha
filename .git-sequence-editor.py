import pathlib, sys
p = pathlib.Path(sys.argv[-1])
s = p.read_text(encoding='utf-8')
s = s.replace('pick ', 'edit ', 1)
p.write_text(s, encoding='utf-8')
