import sys
sys.stdout.reconfigure(encoding='utf-8')
import win32gui

# 获取QClaw窗口的完整标题
hwnd = win32gui.FindWindow(None, 'QClaw')
if hwnd:
    title = win32gui.GetWindowText(hwnd)
    print(f'Window title: "{title}"')
    
    # 也检查所有可见窗口的标题
    def enum_all(hwnd2, _):
        t = win32gui.GetWindowText(hwnd2)
        if t and ('Token' in t or 'token' in t.lower() or '万' in t or '剩余' in t):
            cls = win32gui.GetClassName(hwnd2)
            rect = win32gui.GetWindowRect(hwnd2)
            print(f'Found: hwnd={hwnd2} class={cls} title="{t}" rect={rect}')
        return True
    
    win32gui.EnumWindows(enum_all, None)
else:
    print('QClaw window not found')
