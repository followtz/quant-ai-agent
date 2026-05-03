import sys
sys.stdout.reconfigure(encoding='utf-8')
import win32gui
import win32ui
from PIL import Image
import ctypes
from datetime import datetime

user32 = ctypes.windll.user32
PrintWindow = user32.PrintWindow
PrintWindow.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint]
PrintWindow.restype = ctypes.c_bool

def capture_window(hwnd):
    rect = win32gui.GetWindowRect(hwnd)
    left, top, right, bottom = rect
    width = right - left
    height = bottom - top
    
    hwndDC = win32gui.GetWindowDC(hwnd)
    mfcDC = win32ui.CreateDCFromHandle(hwndDC)
    saveDC = mfcDC.CreateCompatibleDC()
    
    saveBitMap = win32ui.CreateBitmap()
    saveBitMap.CreateCompatibleBitmap(mfcDC, width, height)
    saveDC.SelectObject(saveBitMap)
    
    result = PrintWindow(hwnd, saveDC.GetSafeHdc(), 3)
    
    bmpinfo = saveBitMap.GetInfo()
    bmpstr = saveBitMap.GetBitmapBits(True)
    
    im = Image.frombuffer('RGB', (bmpinfo['bmWidth'], bmpinfo['bmHeight']), bmpstr, 'raw', 'BGRX', 0, 1)
    
    win32gui.DeleteObject(saveBitMap.GetHandle())
    saveDC.DeleteDC()
    mfcDC.DeleteDC()
    win32gui.ReleaseDC(hwnd, hwndDC)
    
    return im

hwnd = win32gui.FindWindow(None, 'QClaw')
img = capture_window(hwnd)
w, h = img.size
print(f'Window: {w}x{h}')

# 从用户截图(2560x1390)看，"已用31.3万，剩余86%"在右上角
# 它在窗口控制按钮左侧，看起来在标题栏下方或标题栏内
# 用户截图分辨率2560x1390，我们的截图2062x1126
# 比例约 1.24:1

# 尝试多个Y坐标位置
screenshot_dir = r'/home/ubuntu/.openclaw/workspace/scripts/screenshots'
ts = datetime.now().strftime('%Y%m%d_%H%M%S')

# 根据用户截图分析：Token在界面最顶部右侧
# 可能的Y坐标范围：0-50像素（标题栏区域）
regions = [
    # (name, x1, y1, x2, y2)
    ('y0_40',   w-280, 0,   w, 40),
    ('y30_70',  w-280, 30,  w, 70),
    ('y40_80',  w-280, 40,  w, 80),
    ('y0_60',   w-280, 0,   w, 60),
    ('y20_65',  w-280, 20,  w, 65),
    ('y35_75',  w-280, 35,  w, 75),
    # 更宽的区域
    ('wide_y0_50', w-350, 0, w, 50),
    ('wide_y25_75', w-350, 25, w, 75),
]

for name, x1, y1, x2, y2 in regions:
    crop = img.crop((x1, y1, x2, y2))
    path = f'{screenshot_dir}/find_{name}_{ts}.png'
    crop.save(path)
    print(f'{name}: ({x1},{y1},{x2},{y2}) -> {crop.size[0]}x{crop.size[1]}')

# 同时保存完整截图用于参考
img.save(f'{screenshot_dir}/full_{ts}.png')
print(f'Done - full screenshot saved')
