import re
import sys
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

# Automatically managed via update_preserved_names.py. Keep manual edits in preserved_names.
imported_names = ['puts', 'set-print-prefix', 'set-fw-name', 'timeout-reset', 'get-ppm', 'get-ppm-age', 'set-servo', 'get-vin', 'select-motor', 'get-selected-motor', 'set-bms-chg-allowed', 'bms-force-balance', 'bms-zero-offset', 'bms-st', 'get-adc', 'override-temp-motor', 'get-adc-decoded', 'set-aux', 'get-imu-rpy', 'get-imu-quat', 'get-imu-acc', 'get-imu-gyro', 'get-imu-mag', 'get-imu-acc-derot', 'get-imu-gyro-derot', 'recv-data', 'get-remote-state', 'stats', 'set-odometer', 'stats-reset', 'main-init-done', 'shutdown-hold', 'override-speed', 'app-adc-detach', 'app-adc-override', 'app-adc-range-ok', 'app-ppm-detach', 'app-ppm-override', 'app-disable-output', 'app-is-output-disabled', 'app-pas-get-rpm', 'set-current', 'set-current-rel', 'set-duty', 'set-brake', 'set-brake-rel', 'set-handbrake', 'set-handbrake-rel', 'set-rpm', 'set-pos', 'foc-openloop', 'foc-openloop-phase', 'set-kill-sw', 'foc-beep', 'foc-play-tone', 'foc-play-samples', 'foc-play-stop', 'get-current', 'get-current-dir', 'get-current-in', 'get-id', 'get-iq', 'get-id-set', 'get-iq-set', 'get-vd', 'get-vq', 'get-est-lambda', 'get-est-res', 'get-est-ind', 'get-hfi-res', 'get-duty', 'get-rpm', 'get-rpm-fast', 'get-rpm-faster', 'get-rpm-set', 'get-pos', 'get-temp-fet', 'get-temp-mot', 'get-speed', 'get-speed-set', 'get-dist', 'get-dist-abs', 'get-batt', 'get-fault', 'get-ah', 'get-wh', 'get-ah-chg', 'get-wh-chg', 'get-encoder', 'set-encoder', 'get-encoder-error-rate', 'encoder-index-found', 'pos-pid-now', 'pos-pid-set', 'pos-pid-error', 'phase-motor', 'phase-encoder', 'phase-hall', 'phase-observer', 'observer-error', 'phase-all', 'enc-corr', 'enc-corr-en', 'enc-sample', 'setup-ah', 'setup-ah-chg', 'setup-wh', 'setup-wh-chg', 'setup-current', 'setup-current-in', 'setup-num-vescs', 'can-msg-age', 'canset-current', 'canset-current-rel', 'canset-duty', 'canset-brake', 'canset-brake-rel', 'canset-rpm', 'canset-pos', 'canget-current', 'canget-current-in', 'canget-temp-fet', 'canget-temp-motor', 'canget-speed', 'canget-dist', 'canget-ppm', 'can-list-devs', 'can-ping', 'can-local-id', 'can-update-baud', 'can-send-sid', 'can-send-eid', 'can-recv-sid', 'can-recv-eid', 'can-start', 'can-stop', 'can-use-vesc', 'canmsg-recv', 'canmsg-send', 'sin', 'cos', 'tan', 'asin', 'acos', 'atan', 'atan2', 'pow', 'sqrt', 'log', 'log10', 'deg2rad', 'rad2deg', 'throttle-curve', 'rand', 'rand-max', 'raw-adc-current', 'raw-adc-voltage', 'raw-mod-alpha', 'raw-mod-beta', 'raw-mod-alpha-measured', 'raw-mod-beta-measured', 'raw-hall', 'uart-write', 'uart-read-bytes', 'uart-read-until', 'uartcomm-start', 'uartcomm-stop', 'i2c-start', 'i2c-tx-rx', 'i2c-restore', 'i2c-detect-addr', 'imu-start-lsm6', 'imu-stop', 'gpio-read', 'gpio-hold', 'gpio-hold-deepsleep', 'pwm-start', 'pwm-stop', 'pwm-set-duty', 'icu-start', 'icu-width', 'icu-period', 'as5047x-init', 'as5047x-deinit', 'as5047x-angle', 'conf-set', 'conf-store', 'store-backup', 'conf-detect-foc', 'conf-set-pid-offset', 'conf-measure-res', 'conf-measure-ind', 'conf-restore-mc', 'conf-restore-app', 'conf-dc-cal', 'conf-dc-cal-set', 'conf-enc-sincos', 'conf-get-limits', 'conf-detect-lambda-enc', 'conf-detect-hall', 'loopfor', 'foldl', 'foldr', 'zipwith', 'sort', 'str-join', 'str-to-i', 'str-to-f', 'str-cmp-asc', 'str-cmp-dsc', 'str-len', 'str-find', 'to-str-delim', 'bufclear', 'buf-resize', 'load-native-lib', 'unload-native-lib', 'uavcan-last-rawcmd', 'uavcan-last-rpmcmd', 'lbm-set-quota', 'lbm-set-gc-stack-size', 'image-save', 'mutex-create', 'mutex-lock', 'mutex-unlock', 'plot-init', 'plot-add-graph', 'plot-set-graph', 'plot-send-points', 'ioboard-get-adc', 'ioboard-get-digital', 'ioboard-set-digital', 'ioboard-set-pwm', 'log-config-field', 'log-start', 'log-stop', 'log-send-f32', 'log-send-f64', 'gnss-lat-lon', 'gnss-height', 'gnss-speed', 'gnss-hdop', 'gnss-date-time', 'gnss-age', 'ublox-init', 'nmea-parse', 'set-pos-time', 'cmds-start-stop', 'cmds-proc', 'esp-now-recv', 'wifi-get-bw', 'wifi-set-bw', 'wifi-stop', 'wifi-start', 'f-connect', 'f-connect-nand', 'f-disconnect', 'f-open', 'f-close', 'f-read', 'f-readline', 'f-write', 'f-tell', 'f-seek', 'f-mkdir', 'f-rm', 'f-ls', 'f-size', 'f-rename', 'f-sync', 'f-fatinfo', 'fw-erase', 'fw-write', 'fw-reboot', 'fw-info', 'fw-data', 'fw-write-raw', 'lbm-erase', 'qml-erase', 'lbm-write', 'qml-write', 'lbm-run', 'rgbled-deinit', 'color-add', 'color-sub', 'color-scale', 'unzip', 'zip-ls', 'aes-ctr-crypt', 'sleep-deep', 'sleep-light', 'sleep-config-wakeup-pin', 'rtc-data', 'connected-wifi', 'connected-hub', 'connected-ble', 'connected-usb', 'nvs-erase', 'nvs-qml-erase', 'nvs-qml-init', 'nvs-read', 'nvs-qml-read', 'nvs-write', 'nvs-qml-write', 'nvs-qml-erase-partition', 'nvs-list', 'nvs-qml-list']

all_preserved_names = preserved_names + imported_names

def generate_short_names():
    # Generate short names: a, b, c, ..., z, aa, ab, ac, ...
    chars = string.ascii_lowercase
    for length in range(1, 4):  # Adjust range for longer names if needed
        yield from (
            ''.join(combination)
            for combination in generate_combinations(chars, length)
            if ''.join(combination) not in keyword.kwlist and ''.join(combination) not in all_preserved_names
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
                if name not in all_preserved_names}
    
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

def main():
    # Read the input file
    with open(sys.argv[1], 'r') as file:
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
    out = sys.argv[1].replace('.lbm', '_obf.lbm')
    with open(out, 'w') as file:
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

    print(f"\nMinimized code has been written to {out}")

if __name__ == '__main__':
    main()