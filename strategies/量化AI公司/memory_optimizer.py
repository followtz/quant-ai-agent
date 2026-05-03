# -*- coding: utf-8 -*-
import psutil
import os
import gc
from datetime import datetime

def get_python_processes():
    trading_procs = ['v4_live_engine', 'prev_close_v2', 'monitor', 'v4_monitor', 
                     'check_pos', 'v4_monitor_enhanced', 'btdr', 'lianlian']
    procs = []
    for p in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            if p.info['name'] and 'python' in p.info['name'].lower():
                cmdline = ' '.join(p.info['cmdline'] or [])
                procs.append({
                    'pid': p.info['pid'],
                    'cmdline': cmdline,
                    'mem_mb': round(p.memory_info().rss / 1024 / 1024, 1),
                    'is_trading': any(t in cmdline.lower() for t in trading_procs)
                })
        except:
            pass
    return sorted(procs, key=lambda x: x['mem_mb'], reverse=True)

def get_memory_info():
    vm = psutil.virtual_memory()
    return {
        'total_gb': round(vm.total / 1024**3, 2),
        'used_gb': round(vm.used / 1024**3, 2),
        'free_gb': round(vm.available / 1024**3, 2),
        'percent': vm.percent
    }

def cleanup_temp_files():
    temp_dirs = [os.environ.get('TEMP', ''), os.environ.get('TMP', '')]
    cleaned = 0
    for d in temp_dirs:
        if d and os.path.exists(d):
            for f in os.listdir(d):
                try:
                    path = os.path.join(d, f)
                    if os.path.isfile(path) and (datetime.now().timestamp() - os.path.getmtime(path)) > 86400:
                        cleaned += os.path.getsize(path)
                        os.remove(path)
                except:
                    pass
    return cleaned / 1024 / 1024

def force_gc():
    collected = gc.collect()
    return collected

print("=" * 60)
print("  Lobster Quant Server - Memory Optimizer")
print("=" * 60)

mem = get_memory_info()
print(f"\n[Memory Status]")
print(f"  Total:   {mem['total_gb']} GB")
print(f"  Used:    {mem['used_gb']} GB ({mem['percent']}%)")
print(f"  Available: {mem['free_gb']} GB")

print(f"\n[Python Trading Processes]")
py_procs = get_python_processes()
for p in py_procs:
    tag = "[LIVE] " if p['is_trading'] else "[SAFE] "
    name = os.path.basename(p['cmdline'].split(' --')[0].split('.py')[0] + '.py') if '.py' in p['cmdline'] else 'python'
    print(f"  {tag}PID {p['pid']:>5} | {p['mem_mb']:>6.1f} MB | {name}")

gc_count = force_gc()
temp_mb = cleanup_temp_files()

mem_after = get_memory_info()
freed = mem_after['free_gb'] - mem['free_gb']

print(f"\n[Cleanup Results]")
print(f"  GC: {gc_count} objects collected")
print(f"  Temp files: {temp_mb:.1f} MB cleaned")
print(f"  Available after: {mem_after['free_gb']} GB (freed {freed:.2f} GB)")

if mem_after['percent'] > 90:
    print(f"\n[!] WARNING: Memory usage {mem_after['percent']}% - consider upgrading to 8GB+")
elif mem_after['percent'] > 80:
    print(f"\n[~] Memory usage {mem_after['percent']}% - monitor closely")
else:
    print(f"\n[OK] Memory usage {mem_after['percent']}% - normal")

print("=" * 60)
