import sys
sys.stdout.reconfigure(encoding='utf-8')
import win32gui
import win32ui
import win32con
from PIL import Image
import ctypes

# 定义PrintWindow函数
user32 = ctypes.windll.user32
PrintWindow = user32.PrintWindow
PrintWindow.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint]
PrintWindow.restype = ctypes.c_bool

def capture_window(hwnd):
    # 获取窗口尺寸（包含非客户区如标题栏）
    rect = win32gui.GetWindowRect(hwnd)
    left, top, right, bottom = rect
    width = right - left
    height = bottom - top
    
    # 创建设备上下文
    hwndDC = win32gui.GetWindowDC(hwnd)
    mfcDC = win32ui.CreateDCFromHandle(hwndDC)
    saveDC = mfcDC.CreateCompatibleDC()
    
    saveBitMap = win32ui.CreateBitmap()
    saveBitMap.CreateCompatibleBitmap(mfcDC, width, height)
    saveDC.SelectObject(saveBitMap)
    
    # 使用PrintWindow捕获整个窗口（包括标题栏）
    result = PrintWindow(hwnd, saveDC.GetSafeHdc(), 3)
    
    bmpinfo = saveBitMap.GetInfo()
    bmpstr = saveBitMap.GetBitmapBits(True)
    
    im = Image.frombuffer(
        'RGB',
        (bmpinfo['bmWidth'], bmpinfo['bmHeight']),
        bmpstr, 'raw', 'BGRX', 0, 1)
    
    win32gui.DeleteObject(saveBitMap.GetHandle())
    saveDC.DeleteDC()
    mfcDC.DeleteDC()
    win32gui.ReleaseDC(hwnd, hwndDC)
    
    return im, (left, top, right, bottom)

# 找到QClaw窗口
hwnd = win32gui.FindWindow(None, 'QClaw')
if not hwnd:
    print('QClaw window not found')
    exit(1)

img, rect = capture_window(hwnd)
w, h = img.size
print(f'Full window: {w}x{h}, rect={rect}')

# 保存完整截图
img.save(r'C:\Users\Administrator\.qclaw\workspace-agent-40f5a53e\scripts\screenshots\qclaw_full.png')
print('Full screenshot saved')

# 裁剪右上角区域（包含标题栏）
regions = [
    ('top_right_300x80', (w-300, 0, w, 80)),
    ('top_right_400x60', (w-400, 0, w, 60)),
    ('top_right_500x100', (w-500, 0, w, 100)),
    ('top_bar', (0, 0, w, 40)),
]

for name, box in regions:
    crop = img.crop(box)
    safe_name = name.replace(' ', '_')
    filename = rf'C:\Users\Administrator\.qclaw\workspace-agent-40f5a53e\scripts\screenshots\corner_{safe_name}.png'
    crop.save(filename)
    print(f'{name}: {box} -> {crop.size[0]}x{crop.size[1]}')
