import re
def valid_hex_color(value): return bool(re.fullmatch(r'#[0-9a-fA-F]{6}',value or ''))
def valid_password(value): return len(value or '')>=8
def clean_key(value): return re.sub(r'[^A-Z0-9_-]+','_',value.upper().strip()).strip('_')
