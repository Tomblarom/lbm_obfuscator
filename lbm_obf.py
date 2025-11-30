import re
import string
import keyword
# List of special constructs and functions to preserve
# Has some hacks such as including preserved words in strings (instead of proper regex to ignore things in between quotes), including import statement and new line inclusions for import statement.
preserved_names = [
    # LispBM keywords and special forms
    'def', 'defun', 'defunret', 'let', 'if', 'cond', 'case', 'and', 'or', 'not',
    'lambda', 'fn', 'loop', 'while', 'prog1', 'prog2', 'progn', 'eval', 'apply',
    'map', 'filter', 'reduce', 'concat', 'append', 'reverse', 'flatten', 'length',
    'list', 'cons', 'car', 'cdr', 'setq', 'setvar', 'define', 'define-macro', 'go', 'do', 'return', 'nil', 'match', 'break', 'var', 'eq', 'value', 'little-endian', 'free', 't', 'read', 'b','i','f','not','running','on','timeout','x', 'gc', 'color-mix', 'to-i32', 'str-replace', 'can-cmd',
    
    # LispBM-specific constructs
    'const-start', 'const-end', 'const-symbol-strings', 'no-gc',
    
    # Buffer operations
    'bufcreate', 'bufcpy', 'bufget-u8', 'bufget-u16', 'bufget-u32', 'bufget-i8', 
    'bufget-i16', 'bufget-i32', 'bufget-f32', 'bufset-u8', 'bufset-u16', 'bufset-u32', 
    'bufset-i8', 'bufset-i16', 'bufset-i32', 'bufset-f32', 'buflen', 'move-to-flash', 'get-mac-addr',
    
    # Math and bitwise operations
    'abs', 'min', 'max', 'floor', 'ceil', 'round', 'mod', 'clip', 'bits-enc-int',
    'bits-dec-int', 'eq', 'not-eq', 'bitwise-and', 'bitwise-or','crc32','crc16', 'crc',
    
    # Type conversions
    'to-str', 'to-float', 'to-i', 'type-of', 'to-u',
    
    # List and array operations
    'first', 'rest', 'nth', 'set-nth', 'assoc', 'setassoc', 'cossa', 'ix', 'setix',
    'array-create', 'array-copy', 'second', 'range', 'take',
    
    # String operations
    'str-from-n', 'str-merge', 'str-cmp', 'str-split', 'str-part', 'str-to-lower',
    'str-to-upper', 'to-str',
        
    # System and I/O functions
    'print', 'exit-error', 'send-data', 'recv', 'event-register-handler', 'event-enable',
    'spawn', 'sleep', 'sysinfo', 'systime', 'secs-since', 'pin-mode-out', 'pin-mode-in-pu', 'uart-read', 'uart-stop', 'exit-ok',
        
    # VESC-specific functions
    'can-scan', 'canget-rpm', 'canget-vin', 'canget-duty', 'canget-adc',
    'gpio-configure', 'gpio-write', 'uart-start', 'uart-read', 'rcode-run', 
    'rcode-run-noret', 'set-bms-val', 'get-bms-val', 'rgbled-init', 'rgbled-update',
    'rgbled-color', 'rgbled-buffer', 'get-mac-addr', 'wifi-set-chan', 'wifi-get-chan',
    'esp-now-start', 'esp-now-add-peer', 'esp-now-del-peer', 'esp-now-send', 'import', 'pkg', 'lib_code_server', 'code_server', 'vescpkg',
    'read-eval-program', 'sysinfo', 'fw-ver', 'event-esp-now-rx', 'event-data-rx', 'send-bms-can', 'bms-temp-ic', 'bms-temps-adc', 'bms-i-in-ic', 'bms-v-cell', 'bms-cell-num', 'bms-temp-adc-num','bms-temp-cell-max','set-remote-state','jsy','jsx','bt-c','bt-z','is-rev','conf-get','si-battery-cells', 'bms-soc', 'code-server', 'pkg', 'canget-current-dir',
    
    # EEPROM operations
    'eeprom-read-i', 'eeprom-read-f', 'eeprom-store-i', 'eeprom-store-f',
    
    # Color operations
    'color-make', 'color-split', 'setcdr',
    
    # Looping constructs
    'loopwhile', 'loopwhile-thd', 'looprange', 'loopforeach', 'yield',
	
	'Settings', 'Saved', 'msg','d','hw-type','hw-express', 'send-config', 'restore-config','save-config','recv-config', 'settings', 'third', 'corrupt', 'Error', 'Restored', 'Read', 'trap', 'status', 'Invalid', 'Pin', 'bms-v-tot', 'atomic', 'pair-pubmote', 'wifi-get-chan', 'wifi-mode', 'WiFi', 'is', 'disabled','Please','enable', 'and', 'reboot', 'gc',
]

def generate_short_names():
    # Generate short names: a, b, c, ..., z, aa, ab, ac, ...
    chars = string.ascii_lowercase
    for length in range(1, 4):  # Adjust range for longer names if needed
        yield from (
            ''.join(combination)
            for combination in generate_combinations(chars, length)
            if ''.join(combination) not in keyword.kwlist and ''.join(combination) not in preserved_names
        )

def generate_combinations(chars, length):
    if length == 1:
        for char in chars:
            yield (char,)
    else:
        for char in chars:
            for suffix in generate_combinations(chars, length - 1):
                yield (char,) + suffix

def remove_comments(code):
    # Remove comments (everything from ; to the end of the line)
    return re.sub(r';.*$', '', code, flags=re.MULTILINE)

def minimize_names(code):
    # Find all variable names (excluding those starting with @)
    name_pattern = r'\b(?!@)([a-zA-Z@][a-zA-Z0-9@-]*)\b'  # Updated pattern to include @ in names
    names = re.findall(name_pattern, code)
    
    # Find all constant-style names (all caps with underscores)
    constant_pattern = r'\b[A-Z][A-Z0-9_]+\b'
    constants = re.findall(constant_pattern, code)
    
    # Create a mapping of original names to short names
    short_names = generate_short_names()
    name_map = {name: next(short_names) for name in set(names + constants) 
                if name not in preserved_names}
    
    # Replace names in the code
    def replace_name(match):
        name = match.group(0)
        if name.startswith('@'):
            return name  # Preserve names starting with @
        return name_map.get(name, name)  # Replace name if it exists in the mapping

    code = re.sub(name_pattern, replace_name, code)
    code = re.sub(constant_pattern, replace_name, code)
    
    return code, name_map
	
def remove_unnecessary_whitespace(code):
    # Remove leading/trailing whitespace from each line
    code = '\n'.join(line.strip() for line in code.split('\n'))
    
    # Remove extra spaces between tokens
    code = re.sub(r'\s+', ' ', code)

    # Remove spaces around parentheses and quotes
    code = re.sub(r'\s*([()])\s*', r'\1', code)
    code = re.sub(r'\s*([\'"])\s*', r'\1', code)
    # Remove spaces before commas and preserve one space after
    code = re.sub(r'\s*,\s*', ', ', code)
    
    # Remove newlines between closing and opening parentheses
    #code = re.sub(r'\)\s*\n\s*\(', ')(', code)
    
    # Preserve newlines for readability (optional, remove if you want maximum minimization)
    #code = re.sub(r'([^\s])\(', r'\1\n(', code)
    code = code.replace(
        '(import"pkg@://vesc_packages/lib_code_server/code_server.vescpkg"\'code-server)(read-eval-program code-server)',
        '\n(import "pkg@://vesc_packages/lib_code_server/code_server.vescpkg" \'code-server)\n(read-eval-program code-server)'
    )
    code = code.replace(
        'settings',
        'settings '
    )
    code = code.replace(
        '(set-remote-state',
        '(set-remote-state '
    )
    code = code.replace(
        'msg',
        'msg '
    )
    code = code.replace(
        'status',
        'status '
    )
    code = code.replace(
        '%d',
        '%d '
    )
    code = code.replace(
        '%.2f',
        '%.2f '
    )
	
    return code.strip()

# Read the input file
with open('float-accessories.lisp', 'r') as file:
    original_code = file.read()

# Get the original file size
original_size = len(original_code)

# Remove comments
code_without_comments = remove_comments(original_code)

# Minimize the code
minimized_code, name_mapping = minimize_names(code_without_comments)

# Remove unnecessary whitespace
minimized_code = remove_unnecessary_whitespace(minimized_code)

# Get the minimized file size
minimized_size = len(minimized_code)

# Write the minimized code to a new file
with open('float-accessories-minimized-code.lisp', 'w') as file:
    file.write(minimized_code)

# Print the name mapping for reference
print("Name mapping:")
for original, short in name_mapping.items():
    print(f"{original} -> {short}")

# Calculate and print compression statistics
bytes_saved = original_size - minimized_size
compression_ratio = (bytes_saved / original_size) * 100

print(f"\nOriginal size: {original_size} bytes")
print(f"Minimized size: {minimized_size} bytes")
print(f"Bytes saved: {bytes_saved} bytes")
print(f"Compression ratio: {compression_ratio:.2f}%")

print("\nMinimized code has been written to 'minimized_code.lisp'")