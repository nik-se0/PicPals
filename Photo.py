# Standard Library
import ctypes
import os
import shutil
import sys
import threading
import time
import textwrap
from typing import Callable, Optional
import io
import logging

# Third-Party Libraries
import cv2
import imagehash
import numpy as np
import scipy._cyutility
from PIL import ExifTags, Image, ImageFilter
import win32com.client
import easyocr
from typing import Optional, Callable

# GUI
import tkinter as tk
from tkinter import filedialog, messagebox, ttk 
import tkinter.font as tkfont


#Inside of the code
def _report_callback_exception(self, exc, val, tb):
    logger.error("Unhandled exception in Tk callback", exc_info=(exc, val, tb))
tk.Tk.report_callback_exception = _report_callback_exception

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE  = os.path.join(BASE_DIR, "logs_ERROR.log")
logging.basicConfig(level    = logging.ERROR,filename = LOG_FILE,filemode = "a",format   = "%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

#Группировка по схожести
METHODS_DATA = {
    '1': { "rus": "Average Hash",
            "desc": "Cравнивает каждый пиксель со средней яркостью всех пикселей.",
            "size": "8×8",
            "mode": "ЧБ",
            "func": imagehash.average_hash},
    '2': { "rus": "RGB Average Hash",
            "desc": "Вычисляет средней яркостью для R, G и B по-отдельности и объединяет три результата в один вектор.",
            "size": "8×8×3",
            "mode": "Цвет",
            "func": None},
    '3': { "rus": "Difference Hash",
            "desc": "Сравнивает яркость соседних пикселей в строках.",
            "size": "9×8",
            "mode": "ЧБ",
            "func": imagehash.dhash},
    '4': { "rus": "Perceptual Hash",
            "desc": "Преобразует пространственные данные в частотную область и сравнивает среднюю амплитуду колебаний низких частот (без шумов и деталей)",
            "size": "32×32",
            "mode": "ЧБ",
            "func": imagehash.phash},
    '5': {"rus": "RGB Perceptual Hash",
            "desc": "Запускает Perceptual Hash для каждого из каналов R, G и B и объединяет их в итоговый вектор.",
            "size": "32×32×3",
            "mode": "Цвет",
            "func": None},
    '6': {"rus": "Wavelet Hash",
            "desc": "С помощью функции Хаара, изобраджение раскладывается на две части: грубую картинку и мелкие детали. Из всех полученных коэффициентов выбираются только приближённые, для сравнения со средним значением (медианой)",
            "size": "—",
            "mode": "ЧБ",
            "func": imagehash.whash},
    '7': {"rus": "HSV Color Hash",
            "desc": "Преобразует в HSV, строит 3D-гистограмму по H, S, V.",
            "size": "bins³",
            "mode": "Цвет",
            "func": None},
    '8': { "rus": "RGB Histogram Hash",
            "desc": "Квантизирует RGB-каналы, строит 3D-гистограмму.",
            "size": "bins³",
            "mode": "Цвет",
            "func": None},
    '9': {'rus': 'Blur + Avg Hash',
            'desc': 'GaussianBlur → AvgHash по каждому RGB-каналу.',
            'size': '8×8×3',
            'mode': 'Цвет',
            'func': None},
    '10': {'rus': 'Blur + PHash',
            'desc': 'GaussianBlur → PHash по каждому RGB-каналу.',
            'size': '16×16×3',
            'mode': 'Цвет',
            'func': None},
    '11': { 'rus': 'Color Moments Hash',
            'desc': 'Блоки → mean/var по каналам → биты по отношению к глобальным.',
            'size': 'bins³×3×2',
            'mode': 'Цвет',
            'func': None},}

# Реализация цветных методов
def hsv_color_hash(img, bins=8):
    hsv = np.array(img.convert('HSV')).reshape(-1, 3)
    hist, _ = np.histogramdd(hsv, bins=(bins,)*3, range=((0,255),)*3)
    flat = hist.flatten(); m = np.median(flat)
    return (flat > m).astype(int)
def rgb_avg_hash(img):
    r, g, b = img.convert('RGB').split()
    bits = []
    for ch in (r, g, b):
        bits.append(np.array(imagehash.average_hash(ch).hash).flatten())
    return np.concatenate(bits).astype(int)
def rgb_phash(img):
    r, g, b = img.convert('RGB').split()
    bits = []
    for ch in (r, g, b):
        bits.append(np.array(imagehash.phash(ch).hash).flatten())
    return np.concatenate(bits).astype(int)
def rgb_hist_hash(img, bins=8):
    arr = np.array(img.convert('RGB')).reshape(-1,3)
    hist, _ = np.histogramdd(arr, bins=(bins,)*3, range=((0,255),)*3)
    flat = hist.flatten(); m = np.median(flat)
    return (flat > m).astype(int)
def blur_avg_hash(img, hash_size=8, blur_radius=30):
    blurred = img.convert('RGB').filter(ImageFilter.GaussianBlur(radius=blur_radius))
    bits = []
    for ch in blurred.split():
        bits.append(np.array(imagehash.average_hash(ch, hash_size=hash_size).hash).flatten())
    return np.concatenate(bits).astype(int)
def blur_phash(img, hash_size=16, blur_radius=30):
    blurred = img.convert('RGB').filter(ImageFilter.GaussianBlur(radius=blur_radius))
    bits = []
    for ch in blurred.split():
        bits.append(np.array(imagehash.phash(ch, hash_size=hash_size).hash).flatten())
    return np.concatenate(bits).astype(int)
def color_moments_hash(img, grid=(4, 4)):
    rgb = img.convert('RGB')
    arr = np.array(rgb)
    h, w = arr.shape[:2]
    gx, gy = grid
    by, bx = h//gy, w//gx

    # глобальные пороги
    global_mean = arr.mean(axis=(0,1))
    global_var  = arr.var(axis=(0,1))

    bits = []
    for i in range(gy):
        for j in range(gx):
            block = arr[i*by:(i+1)*by, j*bx:(j+1)*bx]
            bm = block.mean(axis=(0,1))
            bv = block.var(axis=(0,1))
            # сначала биты для mean, потом для var
            bits.extend((bm > global_mean).astype(int))
            bits.extend((bv > global_var ).astype(int))
    return np.array(bits)

# Привязка функций
METHODS_DATA['2']['func']  = hsv_color_hash
METHODS_DATA['5']['func']  = rgb_avg_hash
METHODS_DATA['7']['func']  = rgb_phash
METHODS_DATA['8']['func']  = rgb_hist_hash
METHODS_DATA['9']['func'] = blur_avg_hash
METHODS_DATA['10']['func'] = blur_phash
METHODS_DATA['11']['func'] = color_moments_hash

def create_unique_folder(base_path, folder_name):
    parent_dir = os.path.dirname(os.path.abspath(base_path))
    result_path = os.path.join(parent_dir, folder_name)
    counter = 1

    while os.path.exists(result_path):
        result_path = os.path.join(parent_dir, f"{folder_name} ({counter})")
        counter += 1
    os.makedirs(result_path, exist_ok=True)
    return result_path
def prefix_path(p: str) -> str:
    if os.name != 'nt': return p
    abs_p = os.path.abspath(p)
    if abs_p.startswith('\\\\?\\'): return abs_p
    if abs_p.startswith('\\\\'):
        return '\\\\?\\UNC\\' + abs_p.lstrip('\\')
    return '\\\\?\\' + abs_p
def is_image_file(f: str) -> bool:
    return f.lower().endswith(('.jpg','.jpeg','.png','.bmp','.gif','.tiff'))
def safe_copy(src: str, dst: str):
    os.makedirs(prefix_path(dst), exist_ok=True)
    dstp = os.path.join(dst, os.path.basename(src))
    shutil.copy(prefix_path(src), prefix_path(dstp))
def create_shortcut(src: str, dst: str) -> bool:
    os.makedirs(prefix_path(dst), exist_ok=True)
    name, _ = os.path.splitext(os.path.basename(src))
    link = os.path.join(dst, name + '.lnk')
    i = 1
    while os.path.exists(link):
        link = os.path.join(dst, f"{name}_{i}.lnk"); i += 1
    try:
        shell = win32com.client.Dispatch("WScript.Shell")
        sc = shell.CreateShortcut(link)
        sc.TargetPath       = src
        sc.WorkingDirectory = os.path.dirname(src)
        #sc.IconLocation     = src
        sc.save()
        return True
    except:
        safe_copy(src, dst)
        return False
def resolve_shortcut(path):
    try:
        from win32com.client import Dispatch
    except ImportError:
        return path
    shell = Dispatch('WScript.Shell')
    shortcut = shell.CreateShortCut(path)
    return shortcut.Targetpath or path
def filter_folder(n: int,src: str = '',method=None,threshold: Optional[float] = None,action: Optional[str] = None,progress_callback: Optional[Callable[[int, int], None]] = None,summary_callback: Optional[Callable[[dict], None]] = None):
    if n != 3:
        flag = 1
    else:
        action = '2'
        flag = 0
    all_files = []
    if n == 3:
        for entry in os.scandir(src):
            if entry.is_file() and (is_image_file(entry.name) or entry.name.lower().endswith('.lnk')):
                all_files.append(entry.path)
    else:
        for root_dir, _, filenames in os.walk(src):
            for f in filenames:
                full = os.path.join(root_dir, f)
                if os.path.isfile(full) and (is_image_file(f) or f.lower().endswith('.lnk')):
                    all_files.append(full)
    total = len(all_files)
    if flag == 1:
        result = create_unique_folder(src, "Результат фильтрации")
    else:
        result = src
    os.makedirs(result, exist_ok=True)
    def _draw(cur, tot):
            progress_callback(cur, tot)
    start       = time.time()
    proc        = 0
    clusters    = []
    group_count = 0
    succ = fail = 0
    for path in all_files:
        proc += 1
        fname = os.path.basename(path)
        if n == 3 and fname.lower().endswith('.lnk'):
            real = resolve_shortcut(path)
            compare_path = real if os.path.exists(real) and is_image_file(real) else path
        else:
            compare_path = path
        try:
            with Image.open(compare_path) as img:
                if img.mode == 'P':
                    img = img.convert('RGBA')
                elif img.mode not in ('RGB', 'RGBA'):
                    img = img.convert('RGB')
                hsh  = method(img)
                bits = getattr(hsh, 'hash', hsh).flatten()
        except Exception as e:
            logger.exception(f"{method.__name__} failed on {compare_path}")
            _draw(proc, total)
            continue
        placed = False
        for cl in clusters:
            dist = (bits != cl['bits']).sum()
            sim  = (1 - dist / len(bits)) * 100
            if sim >= threshold:
                placed = True
                cl['count'] += 1
                if cl['count'] == 2:
                    group_count += 1
                    grp = os.path.join(result, f"Группа_{group_count}")
                    os.makedirs(grp, exist_ok=True)
                    cl['group_dir'] = grp
                    if action == '1':
                        create_shortcut(cl['first_path'], grp)
                    else:
                        safe_copy(cl['first_path'], grp)
                tgt = cl['group_dir']
                if action == '1':
                    if create_shortcut(path, tgt):
                        succ += 1
                    else:
                        fail += 1
                else:
                    safe_copy(path, tgt)
                break
        if not placed:
            clusters.append({'bits'       : bits,'count'      : 1,'first_path' : path,'group_dir'  : None})
        _draw(proc, total)
    if action != '1':
        others = os.path.join(result, "Остальные")
        os.makedirs(others, exist_ok=True)
        for cl in clusters:
            if cl['count'] == 1:
                safe_copy(cl['first_path'], others)
    if n == 3:
        for path in all_files:
            if path.lower().endswith('.lnk'):
                try: os.remove(path)
                except OSError: pass
    elapsed = time.time() - start
    groups  = sum(1 for c in clusters if c['count'] > 1)
    singles = sum(1 for c in clusters if c['count'] == 1)
    if flag == 1:
        stats = {'elapsed': elapsed,'proc': proc,'total': total,'groups': groups,'singles': singles,'action': action,'succ': succ,'fail': fail,'result': result}
        summary_callback(stats)
    return result

#Группировка по дате
def get_image_date(path):
    try:
        img = Image.open(path)
        exif = img._getexif() or {}
        for tag, val in exif.items():
            name = ExifTags.TAGS.get(tag, tag)
            if name == 'DateTimeOriginal':
                return val.split(' ')[0].replace(':', '-')
    except:
        pass
    ts = os.path.getmtime(path)
    return time.strftime('%Y-%m-%d', time.localtime(ts))
def group_by_date(src: str,mode: int,nested: bool = True, progress_callback: Optional[Callable[[int, int], None]] = None) -> str:
    result = create_unique_folder(src, "Результат группировки")
    os.makedirs(result, exist_ok=True)
    all_images = [os.path.join(root, f) for root, _, files in os.walk(src) for f in files if is_image_file(f)]
    total = len(all_images)
    for idx, path in enumerate(all_images, start=1):
        try:
            date_str = get_image_date(path)               # 'YYYY-MM-DD'
            year, month, day = date_str.split('-')
            if mode == 1:
                sub1, sub2, sub3 = year, None, None
            elif mode == 2:
                sub1, sub2, sub3 = year, f"{year}-{month}", None
            else:
                sub1, sub2, sub3 = year, f"{year}-{month}", f"{year}-{month}-{day}"
            if nested:
                parts = [p for p in (sub1, sub2, sub3) if p]
                target_dir = os.path.join(result, *parts)
            else:
                last = sub3 or sub2 or sub1
                target_dir = os.path.join(result, last)
            os.makedirs(target_dir, exist_ok=True)
            dst = os.path.join(target_dir, os.path.basename(path))
            shutil.copy2(path, dst)
        except Exception:
            logger.exception(f"group_by_date failed on {path}")
            continue
        finally:
            if progress_callback:
                progress_callback(idx, total)
    return result

#Поиск размытых изображений
def delete_blurred(src: str,sharpness_pct: float = 50.0,action: str = '2',progress_callback: Optional[Callable[[int, int], None]] = None,summary_callback: Optional[Callable[[dict], None]] = None) -> str:
    result = create_unique_folder(src, "Размытые")
    os.makedirs(result, exist_ok=True)
    items = []
    for root, _, files in os.walk(src):
        if os.path.abspath(root).startswith(os.path.abspath(result)):
            continue
        for fname in files:
            if is_image_file(fname) or fname.lower().endswith('.lnk'):
                items.append((root, fname))
    total = len(items)
    succ = fail = 0
    var_threshold = sharpness_pct
    for idx, (root, fname) in enumerate(items, start=1):
        path = os.path.join(root, fname)
        if fname.lower().endswith('.lnk'):
            real = resolve_shortcut(path)
            path = real if os.path.exists(real) and is_image_file(real) else path
        img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
        if img is None or img.size == 0:
            if progress_callback: progress_callback(idx, total)
            continue
        try:
            lap = cv2.Laplacian(img, cv2.CV_64F).var()
        except cv2.error:
            logger.exception(f"delete_blurred: CV error on {path}")
            if progress_callback: progress_callback(idx, total)
            continue
        if lap < var_threshold:
            try:
                if action == '1':
                    if create_shortcut(path, result): succ += 1
                    else: fail += 1
                else:
                    safe_copy(path, result)
                succ += (action == '2')
            except Exception:
                logger.exception(f"delete_blurred: failed to copy/shortcut {path}")
                fail += 1
        if progress_callback:
            progress_callback(idx, total)
    return result

#Поиск текста/скриншотов
def find_text_images(src_dir: str,min_chars: int = 20,lang_list: Optional[list] = None,action: str = '2',progress_callback: Optional[Callable[[int, int], None]] = None,max_side: int = 2000) -> str:
    if lang_list is None:
        lang_list = ['en', 'ru']
    reader = easyocr.Reader(lang_list, gpu=False)
    result_dir = create_unique_folder(src_dir, "С текстом")
    os.makedirs(result_dir, exist_ok=True)
    all_images = [os.path.join(root, fn) for root, _, files in os.walk(src_dir) for fn in files if is_image_file(fn) or fn.lower().endswith('.lnk')]
    total = len(all_images)
    succ = fail = 0
    for idx, full_path in enumerate(all_images, start=1):
        if full_path.lower().endswith('.lnk'):
            real = resolve_shortcut(full_path)
            full = real if os.path.exists(real) and is_image_file(real) else full_path
        else:
            full = full_path
        img = cv2.imread(prefix_path(full))
        if img is None:
            if progress_callback:
                progress_callback(idx, total)
            continue
        h, w = img.shape[:2]
        max_dim = max(h, w)
        if max_dim > max_side:
            scale = max_side / max_dim
            new_w, new_h = int(w * scale), int(h * scale)
            try:
                img = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)
            except Exception:
                logger.exception(f"Ошибка при ресайзе {full}")
        try:
            texts = reader.readtext(img, detail=0, paragraph=True)
            text = " ".join(texts).strip()
        except Exception:
            logger.exception(f"find_text_images failed on {full}")
            text = ""
        if len(text) >= min_chars:
            try:
                if action == '1':
                    if create_shortcut(full, result_dir):
                        succ += 1
                    else:
                        safe_copy(full, result_dir)
                        fail += 1
                else:
                    safe_copy(full, result_dir)
                    succ += 1
            except Exception:
                logger.exception(f"find_text_images: failed to copy/shortcut {full}")
                fail += 1
        if progress_callback:
            progress_callback(idx, total)
    return result_dir


# --- GUI-приложение с меню задач ---
PINK_LIGHT  = "#ffe6f0"     #Палитра розовых оттенков
PINK_MEDIUM = "#ffb3c6"
PINK_DARK   = "#ff80a1"
PINK_ACCENT = "#ff4d75"
menu_width = 0
class PhotoToolApp:
    def __init__(self, root):
        self.root = root

        base_dir  = os.path.dirname(os.path.abspath(__file__))
        icon_path = os.path.join(base_dir, "app.ico")
        if os.path.exists(icon_path):
            self.root.iconbitmap(icon_path)    

        self.root.geometry("512x635")
        self.root.option_add('*Menu.background',    PINK_MEDIUM)
        self.root.option_add('*Menu.foreground',    'black')
        self.root.option_add('*Menu.activeBackground', PINK_DARK)
        self.root.option_add('*Menu.activeForeground', 'white')
        self.root.title("PicPals")
        self.root.configure(bg=PINK_LIGHT)

        style = ttk.Style()             #Настройка ttk-стилей
        style.theme_use("default")
        style.configure("Pink.TLabel",background=PINK_LIGHT,foreground="black")
        style.configure("Pink.TButton",background=PINK_MEDIUM,foreground="black",relief="flat")
        style.map("Pink.TButton",background=[("active", PINK_DARK)],foreground=[("disabled", "#aaa")])
        style.configure("Pink.TCombobox",fieldbackground=PINK_LIGHT,background=PINK_MEDIUM,foreground="black")
        style.configure("Pink.Horizontal.TProgressbar",troughcolor=PINK_LIGHT,background=PINK_ACCENT)
        style.configure("Pink.TLabelframe",background=PINK_LIGHT,bordercolor=PINK_MEDIUM)
        style.configure("Pink.TLabelframe.Label",background=PINK_LIGHT,foreground="black")
        style.map("Pink.TCombobox",fieldbackground=[("readonly", "white")],background=[("readonly", "white")],selectbackground=[("!disabled", PINK_LIGHT)],selectforeground=[("!disabled", "black")])

        self.mode_var = tk.StringVar(value='1')
        self._build_widgets()
        self._reset_state()
        self._on_mode_change('1')

        self.show_delete_buttons = False
        self.is_recursive = False

    def _build_widgets(self):
        pad = {'padx': 8, 'pady': 4}

        menu_frame = tk.Frame(self.root, bg=PINK_MEDIUM)            # Эмулированное меню
        menu_frame.grid(row=0, column=0, columnspan=5, sticky="we")
        btn_opts = dict(bg=PINK_MEDIUM, fg="black", activebackground=PINK_ACCENT, activeforeground="white", relief="flat", padx=8, pady=4)

        self.menu_buttons = {}
        def make_btn(text, mode):
            btn = tk.Button(menu_frame, text=text,command=lambda m=mode: self._on_mode_change(m),**btn_opts)
            btn.pack(side="left")
            self.menu_buttons[mode] = btn

        make_btn("Группировка по схожести", "1")
        make_btn("Группировка по дате",  "2")
        make_btn("Поиск размытых изображений",      "3")
        make_btn("Поиск текста/скриншотов", "4")

        self.root.update_idletasks()
        menu_width  = menu_frame.winfo_reqwidth()
        self.menu_width = menu_width
        self.root.geometry(f"{self.menu_width}x{600}")

        # Фреймы для задач
        self._build_filter_frame(pad)
        self._build_group_frame(pad)
        self._build_blur_frame(pad)
        self._build_text_frame(pad)

    def _on_start(self):
        mode = self.mode_var.get()
        prog   = self.progress
        status = self.status_lbl
        start  = self.start_btn

        self.start_btn.config(state="disabled")
        self.progress['value'] = 0
        self.status_lbl.config(text="Запущено...")

        # выбираем параметры и рабочий поток
        if mode == '1':
            self.show_delete_buttons = False
            self.is_recursive = False
            try:
                self.rec_folder_lbl.grid_remove()
                self.rec_folder_pb.grid_remove()
                self.rec_file_lbl.grid_remove()
                self.rec_file_pb.grid_remove()
                self.summary_frame.grid_remove()
            except AttributeError:
                pass
            src = self.f1_var.get().strip()
            key = self.f1_method.get().split('.')[0]
            m = METHODS_DATA[key]['func']
            thr = self.f1_thr.get()
            act = self.f1_act.get()
            worker = lambda cb: filter_folder(
                n=1, src=src, method=m,
                threshold=thr, action=act,
                progress_callback=cb,
                summary_callback=self._show_summary
            )
        elif mode == '2':
            src = self.f2_var.get().strip()
            gm  = self.f2_mode.get()
            nested = (self.f2_struct.get() == 1)
            worker = lambda cb: group_by_date(src, gm, nested=nested,progress_callback=cb)
        elif mode == '3':
            src = self.f3_var.get().strip()
            thr = self.f3_thr.get()
            act = self.f3_act.get()
            worker = lambda cb: delete_blurred(src,sharpness_pct=thr,action=act,progress_callback=cb)
        elif mode == '4':
            src    = self.f4_var.get().strip()
            mn     = self.f4_min.get()
            act    = self.f4_act.get()
            worker = lambda cb: find_text_images(src_dir=src,min_chars=mn,action=act,progress_callback=cb)

        if not src or not os.path.isdir(src):
            messagebox.showwarning("Ошибка", "Нужно выбрать корректную папку.")
            self.start_btn.config(state="normal")
            self.status_lbl.config(text="Готово")
            return

        def local_update(cur, tot):
            prog['maximum'] = tot
            prog['value']   = cur
            status.config(text=f"Обработано: {cur} из {tot}")

        def local_on_finish(arg=None):
            if isinstance(arg, str):
                self.last_result = arg
                self.last_text_result = arg
                self._update_text_delete_visibility()
            if mode == '3':
                self.last_blur_result = arg
                self._update_blur_delete_visibility()
            prog['value'] = prog['maximum']
            msg = arg if isinstance(arg, str) else f"{arg['elapsed']:.1f} сек" if isinstance(arg, dict) else "Готово"
            status.config(text=msg)
            start.config(state="normal")
            if mode == '1' and self.f1_act.get() == '1' and not self.is_recursive:
                self.del_orig_btn.grid(); self.del_one_btn.grid()
            else:
                self.del_orig_btn.grid_remove(); self.del_one_btn.grid_remove()
            if mode == '1':
                self.recursive_btn.pack(side="left", padx=5)
            else:
                self.recursive_btn.pack_forget()

        def thread_target():
            try:
                res = worker(local_update)
                self.last_result = res
                local_on_finish(res)
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("Ошибка", str(e)))
                self.root.after(0, local_on_finish)

        threading.Thread(target=thread_target, daemon=True).start()

    def _reset_state(self):
        self.mode_var.set('1')
        self._hide_task_frames()
        self.recursive_btn.pack_forget()
        self.start_btn.config(state="normal")
        self.progress['value'] = 0
        self.status_lbl.config(text="Готово")
    def _hide_task_frames(self):
        for f in (self.filter_frame, self.group_frame,
                  self.blur_frame, self.txt_frame):
            f.grid_forget()
    def _on_mode_change(self, mode):
        self.mode_var.set(mode)
        self._hide_task_frames()
        self._update_menu_selection(mode)
        if mode == '1':
            self.start_btn    = self.filter_start_btn
            self.recursive_btn = self.filter_recursive_btn
            self.progress    = self.filter_progress
            self.status_lbl  = self.filter_status
            self.filter_frame.lift()
            self.filter_frame.grid(row=1, column=0, columnspan=5, pady=6, padx=6, sticky="we")
        elif mode == '2':
            self.start_btn    = self.group_start_btn
            self.progress    = self.group_progress
            self.status_lbl  = self.group_status
            self.group_frame.grid(row=1, column=0, columnspan=5, pady=6, padx=6, sticky="we")
        elif mode == '3':
            self.start_btn    = self.blur_start_btn
            self.progress    = self.blur_progress
            self.status_lbl  = self.blur_status
            self.blur_frame.grid(row=1, column=0, columnspan=5, pady=6, padx=6, sticky="we")
        elif mode == '4':
            self.start_btn    = self.txt_start_btn
            self.progress    = self.txt_progress
            self.status_lbl  = self.txt_status
            self.txt_frame.grid(row=1, column=0, columnspan=5, pady=6, padx=6, sticky="we")
        
        # скрываем кнопки, они появятся по готовности
        self.recursive_btn.pack_forget()
        # self.del_btn_frame.grid_forget()
        self.progress['value'] = 0
        self.status_lbl.config(text="Готово")
    def _update_menu_selection(self, selected_mode):
        for mode, btn in self.menu_buttons.items():
            if mode == selected_mode:
                btn.config(bg=PINK_ACCENT, fg="white")
            else:
                btn.config(bg=PINK_MEDIUM, fg="black")
    def _update_progress(self, current: int, total: int):
        self.progress['maximum'] = total
        self.progress['value']   = current
        self.status_lbl.config(
            text=f"Обработано: {current} из {total}"
        )
    def _browse(self, var):
        d = filedialog.askdirectory()
        if d:
            var.set(d)
    def _on_finish(self, message: str = "Готово"):
        self.progress['value'] = self.progress['maximum']
        self.status_lbl.config(text=message)
        self.start_btn.config(state="normal")

        if  self.mode_var.get() == '1':
            self.recursive_btn.pack(side="left", padx=5)
        else:
            self.recursive_btn.pack_forget()

        if self.mode_var.get() == '1' and self.f1_act.get() == '1' and not self.is_recursive:
            self.show_delete_buttons = True
        else:
            self.show_delete_buttons = False
        self._update_delete_buttons_visibility()

    #Группировка по схожести
    def _build_filter_frame(self, pad):
        fw = int(self.menu_width * 0.8)
        self.filter_frame = ttk.LabelFrame(self.root,text="Параметры фильтрации",width=fw,style="Pink.TLabelframe")
        self.filter_frame.configure(padding=8)
        self.filter_frame.grid(row=1, column=0, columnspan=5,pady=6, padx=6, sticky="we")
        self.filter_frame.grid_columnconfigure(0, weight=0)
        self.filter_frame.grid_columnconfigure(1, weight=3)
        self.filter_frame.grid_columnconfigure(2, weight=0)

        tk.Label(self.filter_frame,text="Папка:",bg=PINK_LIGHT,fg="black").grid(row=0, column=0, **pad, sticky="w")
        self.f1_var = tk.StringVar()
        tk.Entry(self.filter_frame,textvariable=self.f1_var,bg="white").grid(row=0, column=1, **pad, sticky="we")
        ttk.Button(self.filter_frame,text="Обзор…",style="Pink.TButton",command=lambda: self._browse(self.f1_var)).grid(row=0, column=2, **pad)

        tk.Label(self.filter_frame,text="Метод:",bg=PINK_LIGHT,fg="black").grid(row=1, column=0, **pad, sticky="w")
        meth = [f"{k}. {v['rus']}" for k, v in METHODS_DATA.items()]
        self.f1_method = ttk.Combobox(self.filter_frame,values=meth,state="readonly",style="Pink.TCombobox")
        self.f1_method.current(0)
        self.f1_method.grid(row=1, column=1, columnspan=2,**pad, sticky="we")

        self.f1_method.bind("<<ComboboxSelected>>",lambda e: self.f1_desc.config(text=""))

        ttk.Button(self.filter_frame,text="Подробнее о методе",style="Pink.TButton",command=self._show_method_info).grid(row=2, column=0, pady=(0, 8))
        self.f1_desc = tk.Label(self.filter_frame,text="", bg=PINK_LIGHT,fg="black",justify="left",anchor="nw", wraplength= 450)
        self.f1_desc.grid(row=2, column=1, columnspan=2,sticky="we", **pad)
        
        tk.Label(self.filter_frame,text="Процент сходства (%):",bg=PINK_LIGHT,fg="black").grid(row=3, column=0, **pad, sticky="w")
        self.f1_thr = tk.Scale(self.filter_frame,from_=0, to=100,orient="horizontal",highlightthickness=0,  bg=PINK_LIGHT,troughcolor=PINK_MEDIUM,fg="black")
        self.f1_thr.set(90)
        self.f1_thr.grid(row=3, column=1, columnspan=2,**pad, sticky="we")

        tk.Label(self.filter_frame,text="Для результата:",bg=PINK_LIGHT,fg="black").grid(row=4, column=0, **pad, sticky="w")
        self.f1_act = tk.StringVar(value='1')
        tk.Radiobutton(self.filter_frame,text="Создавать ярлыки",variable=self.f1_act,value='1',bg=PINK_LIGHT,activebackground=PINK_MEDIUM).grid(row=4, column=1, sticky="w")
        tk.Radiobutton(self.filter_frame,text="Копировать файлы",variable=self.f1_act,value='2',bg=PINK_LIGHT,activebackground=PINK_MEDIUM).grid(row=5, column=1, sticky="w")

        #Кнопки удаления ссылок (скрыта по умолчанию)
        self.del_orig_btn = ttk.Button(self.filter_frame,text="Удалить оригиналы ярлыков ",style="Pink.TButton",command=lambda: self._delete_links(mode=1))
        self.del_orig_btn.grid(row=4, column=2, sticky="w", padx=5)
        self.del_one_btn = ttk.Button(self.filter_frame,text="Оставить по одному в группе",style="Pink.TButton",command=lambda: self._delete_links(mode=2))
        self.del_one_btn.grid(row=5, column=2, sticky="w", padx=5)
        self.del_orig_btn.grid_remove()
        self.del_one_btn.grid_remove()
        self.f1_var.trace_add('write', lambda *args: self._update_delete_buttons_visibility())
        #self.f1_method.bind("<<ComboboxSelected>>", lambda e: self._update_delete_buttons_visibility(0))

        #Прогрессбар + статус
        self.filter_progress = ttk.Progressbar(self.filter_frame,style="Pink.Horizontal.TProgressbar",orient="horizontal", length=int(self.menu_width * 0.9), mode="determinate")
        self.filter_progress.grid(row=6, column=0, columnspan=3, **pad)
        self.filter_status = ttk.Label(self.filter_frame, text="Готово", style="Pink.TLabel")
        self.filter_status.grid(row=7, column=0, columnspan=3, **pad)

        # Прогрессбар рекурсивной обработки: папки
        self.rec_folder_lbl = ttk.Label(self.filter_frame, text="", style="Pink.TLabel")
        self.rec_folder_lbl.grid(row=10, column=0, columnspan=3, **pad, sticky="w")
        self.rec_folder_lbl.grid_remove()
        self.rec_folder_pb = ttk.Progressbar(self.filter_frame,style="Pink.Horizontal.TProgressbar",orient="horizontal", length=int(self.menu_width * 0.9), mode="determinate")
        self.rec_folder_pb.grid(row=11, column=0, columnspan=3, **pad, sticky="we")
        self.rec_folder_pb.grid_remove()

        # Прогрессбар рекурсивной обработки: файлы
        self.rec_file_lbl = ttk.Label(self.filter_frame, text="", style="Pink.TLabel")
        self.rec_file_lbl.grid(row=12, column=0, columnspan=3, **pad, sticky="w")
        self.rec_file_lbl.grid_remove()

        self.rec_file_pb = ttk.Progressbar(self.filter_frame,style="Pink.Horizontal.TProgressbar",orient="horizontal", length=int(self.menu_width * 0.9), mode="determinate")
        self.rec_file_pb.grid(row=13, column=0, columnspan=3, **pad, sticky="we")
        self.rec_file_pb.grid_remove()

        #Контролы
        ctrl = tk.Frame(self.filter_frame, bg=PINK_LIGHT)
        ctrl.grid(row=8, column=0, columnspan=3, **pad)
        self.filter_start_btn = ttk.Button(ctrl, text="Старт", style="Pink.TButton",width=12, command=self._on_start)
        self.filter_start_btn.pack(side="left", padx=5)
        self.filter_recursive_btn = ttk.Button(ctrl, text="Рекурсивно", style="Pink.TButton",width=12, command=self._on_recursive)
        self.filter_recursive_btn.pack(side="left", padx=5)
        self.filter_recursive_btn.pack_forget()  # скрыта по умолчанию

        self.start_btn    = self.filter_start_btn
        self.recursive_btn = self.filter_recursive_btn
        self.progress    = self.filter_progress
        self.status_lbl  = self.filter_status

        self.summary_frame = tk.Frame(self.filter_frame, bg=PINK_LIGHT)
        self.summary_frame.grid(row=9, column=0, columnspan=3,sticky="we", pady=(10,0))
        self.summary_frame.grid_remove()

    def _update_delete_buttons_visibility(self):
        if self.show_delete_buttons:
            self.del_orig_btn.grid()
            self.del_one_btn.grid()
        else:
            self.del_orig_btn.grid_remove()
            self.del_one_btn.grid_remove()
    def _show_method_info(self):
        sel = self.f1_method.get().split('.', 1)[0].strip()
        data = METHODS_DATA.get(sel)
        if not data:
            self.f1_desc.config(text="Описание не найдено")
            return
        txt =f"{data['desc']}\nРазмер: {data['size']}   Режим: {data['mode']}"
        self.f1_desc.config(text=txt)
    def _delete_links(self, mode=1):
        root = getattr(self, 'last_result', '') or ''
        if not root or not os.path.isdir(root):
            logger.error(f"_delete_links: некорректная папка для удаления ссылок: {root}")
            messagebox.showwarning("Ошибка", "Сначала выполните фильтрацию.")
            return
        tasks = []
        for ent in os.scandir(root):
            if ent.is_dir() and ent.name.startswith("Группа_"):
                links = sorted(os.path.join(ent.path, f) for f in os.listdir(ent.path) if f.lower().endswith('.lnk'))
                if links:
                    tasks.extend(links if mode == 1 else links[1:])
        total = len(tasks)
        if total == 0:
            logger.info(f"_delete_links: нет ярлыков для удаления в папке {root}")
            messagebox.showinfo("Инфо", "Нет ярлыков для удаления.")
            return
        self.start_btn.config(state="disabled")
        self.status_lbl.config(text="Удаляем ярлыки…")
        self.progress.config(maximum=total, value=0)

        def worker_del():
            for idx, lnk in enumerate(tasks, start=1):
                try:
                    tgt = resolve_shortcut(lnk)
                    if os.path.isfile(tgt):
                        os.remove(tgt)
                    os.remove(lnk)
                except Exception:
                    logger.exception(f"_delete_links: не удалось удалить {lnk}")
                finally:
                    self.root.after(0, lambda i=idx: self._update_progress(i, total))
            self.root.after(0, lambda: self._on_finish(f"Удалено: {total}"))

        threading.Thread(target=worker_del, daemon=True).start()
    def _on_recursive(self):
        self.del_orig_btn.grid_remove()
        self.del_one_btn.grid_remove()
        self.is_recursive = True
        try:
            self.summary_frame.grid_remove()
        except AttributeError:
            pass

        # проверка режима
        if self.mode_var.get() != '1':
            messagebox.showwarning("Ошибка", "Рекурсия доступна только после фильтрации.")
            return

        src = getattr(self, 'last_result', '')
        if not src or not os.path.isdir(src):
            messagebox.showwarning("Ошибка", "Нет результатов для рекурсии.")
            return

        subs = [d for d in os.listdir(src)
                if os.path.isdir(os.path.join(src, d))]
        total_folders = len(subs)
        if total_folders == 0:
            messagebox.showinfo("Инфо", "Нет подпапок для рекурсии.")
            return

        # параметры фильтрации из UI
        key       = self.f1_method.get().split('.')[0]
        func      = METHODS_DATA[key]['func']
        thr       = self.f1_thr.get()
        act       = self.f1_act.get()

        # показываем оба бара
        self.rec_folder_lbl.config(text=f"Папок: 0/{total_folders}")
        self.rec_folder_pb.config(maximum=total_folders, value=0)
        self.rec_folder_lbl.grid()
        self.rec_folder_pb.grid()

        self.rec_file_lbl.grid()  # текст и бар файлов появятся позже
        self.rec_file_pb.grid()

        self.start_btn.config(state="disabled")
        self.status_lbl.config(text="Рекурсивная фильтрация…")

        def worker_rec():
            for i, folder in enumerate(subs, start=1):
                folder_path = os.path.join(src, folder)
                try:
                    files = [os.path.join(folder_path, f) for f in os.listdir(folder_path) if os.path.isfile(os.path.join(folder_path, f)) and (is_image_file(f) or f.lower().endswith('.lnk'))]    
                    total_files = len(files)
                    self.root.after(0, lambda tf=total_files: self.rec_file_pb.config(maximum=tf, value=0))
                    self.root.after(0, lambda tf=total_files: self.rec_file_lbl.config(text=f"Файлов: 0/{tf}"))
                    def file_cb(cur, tot=total_files):
                        self.root.after(0, lambda: self.rec_file_pb.config(value=cur))
                        self.root.after(0, lambda: self.rec_file_lbl.config(text=f"Файлов: {cur}/{tot}"))
                    filter_folder(n=3,src=folder_path,method=func,threshold=thr,progress_callback=file_cb)
                except Exception:
                    logger.exception(f"Recursive filter_folder failed on {folder_path}")
                    self.root.after(0,lambda p=folder_path: messagebox.showwarning("Ошибка",f"Не удалось обработать папку:\n{p}"))
                finally:
                    self.root.after(0, lambda idx=i: self.rec_folder_pb.config(value=idx))
                    self.root.after(0, lambda idx=i: self.rec_folder_lbl.config(text=f"Папок: {idx}/{total_folders}"))
            self.root.after(0, lambda: self._on_finish("Рекурсивная фильтрация завершена"))

        threading.Thread(target=worker_rec, daemon=True).start()
    def _show_summary(self, stats: dict):
        for w in self.summary_frame.winfo_children():
            w.destroy()
        headers = ["Время работы", "Обработано", "Создано групп", "Вне групп"]
        values  = [f"{stats['elapsed']:.1f} сек", f"{stats['proc']}/{stats['total']}", str(stats['groups']), str(stats['singles'])]
        if stats['action'] == '1':
            headers += ["Ярлыков создано", "Копий не ярлыков"]
            values  += [str(stats['succ']), str(stats['fail'])]
        for col in range(len(headers)):
            self.summary_frame.grid_columnconfigure(col, weight=1)
        for col, h in enumerate(headers):
            tk.Label(self.summary_frame,text=h,bg=PINK_MEDIUM,fg="black",font=("TkDefaultFont", 10, "bold"),borderwidth=1,relief="solid").grid(row=0, column=col, sticky="nsew", padx=1, pady=1)
        for col, v in enumerate(values):
            tk.Label(self.summary_frame,text=v,bg=PINK_LIGHT,fg="black",borderwidth=1,relief="solid").grid(row=1, column=col, sticky="nsew", padx=1, pady=1)
        self.summary_frame.grid()

    #Группировка по дате
    def _build_group_frame(self, pad):
        fw = int(self.menu_width * 0.8)
        self.group_frame = ttk.LabelFrame(self.root,text="Параметры группировки",width=fw,style="Pink.TLabelframe")
        self.group_frame.configure(padding=8)
        self.group_frame.grid(row=1, column=0, columnspan=5,pady=6, padx=6, sticky="w")

        self.group_frame.grid_columnconfigure(0, weight=0)
        self.group_frame.grid_columnconfigure(1, weight=3)
        self.group_frame.grid_columnconfigure(2, weight=0)

        tk.Label(self.group_frame,text="Папка:",bg=PINK_LIGHT,fg="black").grid(row=0, column=0, **pad, sticky="w")

        self.f2_var = tk.StringVar()
        tk.Entry(self.group_frame,textvariable=self.f2_var,width=50,bg="white").grid(row=0, column=1, **pad, sticky="we")
        ttk.Button(self.group_frame,text="Обзор...",style="Pink.TButton",command=lambda: self._browse(self.f2_var)).grid(row=0, column=2, **pad, sticky="w")

        tk.Label(self.group_frame,text="Группировать по:",bg=PINK_LIGHT,fg="black").grid(row=1, column=0, **pad, sticky="w")
        self.f2_mode = tk.IntVar(value=2)
        tk.Radiobutton(self.group_frame,text="Год",variable=self.f2_mode,value=1,bg=PINK_LIGHT,activebackground=PINK_MEDIUM).grid(row=1, column=1, padx=6, sticky="w")
        tk.Radiobutton(self.group_frame,text="Год-Месяц",variable=self.f2_mode,value=2,bg=PINK_LIGHT,activebackground=PINK_MEDIUM).grid(row=2, column=1, padx=6, sticky="w")
        tk.Radiobutton(self.group_frame,text="Год-Месяц-День",variable=self.f2_mode,value=3,bg=PINK_LIGHT,activebackground=PINK_MEDIUM).grid(row=3, column=1, padx=6, sticky="w")

        # Радиокнопки для выбора структуры папок
        tk.Label(self.group_frame,text="Структура папок:",bg=PINK_LIGHT,fg="black"       ).grid(row=4, column=0, sticky="w", **pad)
        self.f2_struct = tk.IntVar(value=1)   # 1 = вложенная, 2 = одноуровневая
        tk.Radiobutton(self.group_frame,text="Вложенная",variable=self.f2_struct,value=1,bg=PINK_LIGHT,activebackground=PINK_MEDIUM).grid(row=4, column=1, sticky="w", padx=6)
        tk.Radiobutton(self.group_frame,text="Одноуровневая",variable=self.f2_struct,value=2,bg=PINK_LIGHT,activebackground=PINK_MEDIUM).grid(row=5, column=1, sticky="w", padx=6)

        #Прогрессбар + статус
        self.group_progress = ttk.Progressbar(self.group_frame,style="Pink.Horizontal.TProgressbar",orient="horizontal", length=int(self.menu_width * 0.9), mode="determinate")
        self.group_progress.grid(row=6, column=0, columnspan=3, **pad)
        self.group_status = ttk.Label(self.group_frame, text="Готово", style="Pink.TLabel")
        self.group_status.grid(row=7, column=0, columnspan=3, **pad)

        #Контролы
        ctrl = tk.Frame(self.group_frame, bg=PINK_LIGHT)
        ctrl.grid(row=8, column=0, columnspan=3, **pad)
        self.group_start_btn = ttk.Button(ctrl, text="Старт", style="Pink.TButton",width=12, command=self._on_start)
        self.group_start_btn.pack(side="left", padx=5)

    #Поиск размытых изображений
    def _build_blur_frame(self, pad):
        fw = int(self.menu_width * 0.8)
        self.blur_frame = ttk.LabelFrame(self.root,text="Удаление размытых",width=fw,style="Pink.TLabelframe")
        self.blur_frame.configure(padding=8)
        self.blur_frame.grid(row=1, column=0, columnspan=5,pady=6, padx=6, sticky="w")
        self.blur_frame.grid_columnconfigure(0, weight=0)
        self.blur_frame.grid_columnconfigure(1, weight=3)
        self.blur_frame.grid_columnconfigure(2, weight=0)

        tk.Label(self.blur_frame,text="Папка:",bg=PINK_LIGHT,fg="black").grid(row=0, column=0, **pad, sticky="w")

        self.f3_var = tk.StringVar()
        tk.Entry(self.blur_frame,textvariable=self.f3_var,width=50,bg="white").grid(row=0, column=1, **pad, sticky="we")
        ttk.Button(self.blur_frame,text="Обзор...",style="Pink.TButton", command=lambda: self._browse(self.f3_var)).grid(row=0, column=2, **pad)

        # Порог резкости в %
        tk.Label(self.blur_frame, text="Порог резкости (%):", bg=PINK_LIGHT, fg="black").grid(row=1, column=0, **pad, sticky="w")
        self.f3_thr = tk.Scale(self.blur_frame,from_=0, to=100,orient="horizontal",highlightthickness=0,bg=PINK_LIGHT,troughcolor=PINK_MEDIUM,fg="black")
        self.f3_thr.set(50)
        self.f3_thr.grid(row=1, column=1, columnspan=2, **pad, sticky="we")
        tk.Label(self.blur_frame, text="0%", bg=PINK_LIGHT).grid(row=2, column=1, sticky="w", padx=pad['padx']) # Подписи 0 и 100
        tk.Label(self.blur_frame, text="100%", bg=PINK_LIGHT).grid(row=2, column=2, sticky="e", padx=pad['padx'])

        # Выбор действия: ярлыки / копировать
        tk.Label(self.blur_frame, text="Действие:", bg=PINK_LIGHT, fg="black").grid(row=3, column=0, **pad, sticky="w")
        self.f3_act = tk.StringVar(value='2')
        tk.Radiobutton(self.blur_frame, text="Создавать ярлыки",variable=self.f3_act, value='1',bg=PINK_LIGHT, activebackground=PINK_MEDIUM).grid(row=3, column=1, sticky="w")
        tk.Radiobutton(self.blur_frame, text="Копировать файлы",variable=self.f3_act, value='2',bg=PINK_LIGHT, activebackground=PINK_MEDIUM).grid(row=4, column=1, sticky="w")

        # Кнопка удаления ярлыков (появится после выполнения)
        self.del_blur_btn = ttk.Button(self.blur_frame,text="Удалить ярлыки",style="Pink.TButton",command=self._delete_blur_links)
        self.del_blur_btn.grid(row=3, column=2, sticky="w", padx=5)
        self.del_blur_btn.grid_remove()
        self.f3_act.trace_add('write', lambda *a: self._update_blur_delete_visibility())

        #Прогрессбар + статус
        self.blur_progress = ttk.Progressbar(self.blur_frame,style="Pink.Horizontal.TProgressbar",orient="horizontal", length=int(self.menu_width * 0.8), mode="determinate")
        self.blur_progress.grid(row=7, column=0, columnspan=3, **pad)
        self.blur_status = ttk.Label(self.blur_frame, text="Готово", style="Pink.TLabel")
        self.blur_status.grid(row=8, column=0, columnspan=3, **pad)

        #Контролы
        ctrl = tk.Frame(self.blur_frame, bg=PINK_LIGHT)
        ctrl.grid(row=9, column=0, columnspan=3, **pad)
        self.blur_start_btn = ttk.Button(ctrl, text="Старт", style="Pink.TButton",width=12, command=self._on_start)
        self.blur_start_btn.pack(side="left", padx=5)

    def _update_blur_delete_visibility(self):
        if getattr(self, 'last_blur_result', '') and self.f3_act.get() == '1':
            self.del_blur_btn.grid()
        else:
            self.del_blur_btn.grid_remove()
    def _delete_blur_links(self):
        root = getattr(self, 'last_blur_result', '')
        if not root or not os.path.isdir(root):
            logger.error(f"_delete_blur_links: некорректная папка для размытых: {root}")
            messagebox.showwarning("Ошибка", "Сначала выполните поиск размытых изображений.")
            return
        tasks = [f for f in os.listdir(root) if f.lower().endswith('.lnk')]
        total = len(tasks)
        if total == 0:
            logger.info(f"_delete_blur_links: нет ярлыков для удаления в {root}")
            messagebox.showinfo("Инфо", "Нет ярлыков для удаления.")
            return
        self.blur_start_btn.config(state="disabled")    
        self.blur_status.config(text="Удаляем ярлыки…")
        self.blur_progress.config(maximum=total, value=0)

        def worker():
            for idx, fname in enumerate(tasks, start=1):
                lnk = os.path.join(root, fname)
                try:
                    tgt = resolve_shortcut(lnk)
                    if os.path.isfile(tgt):
                        os.remove(tgt)
                    os.remove(lnk)
                except Exception:
                    logger.exception(f"_delete_blur_links: не удалось удалить {lnk}")
                finally:
                    self.root.after(0, lambda i=idx: self._update_blur_progress(i, total))
            self.root.after(0, lambda: self._on_blur_finish(f"Удалено: {total}"))

        threading.Thread(target=worker, daemon=True).start()
    def _update_blur_progress(self, cur, tot):
        self.progress['value'] = cur
        self.status_lbl.config(text=f"Удалено: {cur} из {tot}")
    def _on_blur_finish(self, message="Готово"):
        self.progress['value'] = self.progress['maximum']
        self.status_lbl.config(text=message)
        self.start_btn.config(state="normal")
        self._update_blur_delete_visibility()

    #Поиск текста/скриншотов
    def _build_text_frame(self, pad):
        fw = int(self.menu_width * 0.8)
        self.txt_frame = ttk.LabelFrame(self.root,text="Поиск текста/скриншотов",width=fw,style="Pink.TLabelframe")
        self.txt_frame.configure(padding=8)
        self.txt_frame.grid(row=1, column=0, columnspan=5,pady=6, padx=6, sticky="w")
        self.txt_frame.grid_columnconfigure(0, weight=0)
        self.txt_frame.grid_columnconfigure(1, weight=3)
        self.txt_frame.grid_columnconfigure(2, weight=0)

        tk.Label(self.txt_frame,text="Папка:",bg=PINK_LIGHT,fg="black").grid(row=0, column=0, **pad, sticky="w")
        self.f4_var = tk.StringVar()
        tk.Entry(self.txt_frame,textvariable=self.f4_var,width=50,bg="white").grid(row=0, column=1, **pad, sticky="we")
        ttk.Button(self.txt_frame,text="Обзор...",style="Pink.TButton",command=lambda: self._browse(self.f4_var)).grid(row=0, column=2, **pad)

        tk.Label(self.txt_frame,text="Мин. символов текста:",bg=PINK_LIGHT,fg="black").grid(row=1, column=0, **pad, sticky="w")
        self.f4_min = tk.Scale(self.txt_frame,from_=0, to=200,orient="horizontal", highlightthickness=0, length=380,bg=PINK_LIGHT,troughcolor=PINK_MEDIUM,fg="black")
        self.f4_min.set(20)
        self.f4_min.grid(row=1, column=1, columnspan=2,**pad, sticky="we")

        #Выбор действия
        tk.Label(self.txt_frame, text="Для результата:", bg=PINK_LIGHT, fg="black").grid(row=2, column=0, **pad, sticky="w")
        self.f4_act = tk.StringVar(value='2')
        tk.Radiobutton(self.txt_frame, text="Создавать ярлыки",variable=self.f4_act, value='1',bg=PINK_LIGHT, activebackground=PINK_MEDIUM).grid(row=2, column=1, sticky="w")
        tk.Radiobutton(self.txt_frame, text="Копировать файлы",variable=self.f4_act, value='2',bg=PINK_LIGHT, activebackground=PINK_MEDIUM).grid(row=3, column=1, sticky="w")

        # Кнопка удаления ярлыков (скрыта по умолчанию)
        self.del_txt_btn = ttk.Button(self.txt_frame,text="Удалить ярлыки",style="Pink.TButton",command=self._delete_text_links)
        self.del_txt_btn.grid(row=2, column=2, sticky="w", padx=5)
        self.del_txt_btn.grid_remove()
        self.f4_act.trace_add('write', lambda *a: self._update_text_delete_visibility())

        #Прогрессбар + статус
        self.txt_progress = ttk.Progressbar(self.txt_frame,style="Pink.Horizontal.TProgressbar",orient="horizontal", length=int(self.menu_width * 0.8), mode="determinate")
        self.txt_progress.grid(row=7, column=0, columnspan=3, **pad)
        self.txt_status = ttk.Label(self.txt_frame, text="Готово", style="Pink.TLabel")
        self.txt_status.grid(row=8, column=0, columnspan=3, **pad)

        #Контролы
        ctrl = tk.Frame(self.txt_frame, bg=PINK_LIGHT)
        ctrl.grid(row=9, column=0, columnspan=3, **pad)
        self.txt_start_btn = ttk.Button(ctrl, text="Старт", style="Pink.TButton",width=12, command=self._on_start)
        self.txt_start_btn.pack(side="left", padx=5)
    def _update_text_delete_visibility(self):
        root = getattr(self, 'last_text_result', '')
        if root and os.path.isdir(root) and self.f4_act.get() == '1':
            self.del_txt_btn.grid()
        else:
            self.del_txt_btn.grid_remove()
    def _delete_text_links(self):
        root = getattr(self, 'last_text_result', '')
        if not root or not os.path.isdir(root):
            logger.error(f"_delete_text_links: некорректная папка для текста: {root}")
            messagebox.showwarning("Ошибка", "Сначала выполните поиск текста/скриншотов.")
            return
        tasks = [f for f in os.listdir(root) if f.lower().endswith('.lnk')]
        total = len(tasks)  
        if total == 0:
            logger.info(f"_delete_text_links: нет ярлыков для удаления в {root}")
            messagebox.showinfo("Инфо", "Нет ярлыков для удаления.")
            return
        self.txt_start_btn.config(state="disabled")
        self.txt_status.config(text="Удаляем ярлыки…")
        self.txt_progress.config(maximum=total, value=0)

        def worker():   
            for idx, fname in enumerate(tasks, start=1):
                lnk = os.path.join(root, fname)
                try:
                    tgt = resolve_shortcut(lnk) 
                    if os.path.isfile(tgt):
                        os.remove(tgt)
                    os.remove(lnk)
                except Exception:
                    logger.exception(f"_delete_text_links: не удалось удалить {lnk}")
                finally:
                    self.root.after(0, lambda i=idx: self._update_text_progress(i, total))
            self.root.after(0, lambda: self._on_text_finish(f"Удалено: {total}"))

        threading.Thread(target=worker, daemon=True).start()
    def _update_text_progress(self, cur, tot):
        self.txt_progress['value'] = cur
        self.txt_status.config(text=f"Удалено: {cur} из {tot}")
    def _on_text_finish(self, message="Готово"):
        self.txt_progress['value'] = self.txt_progress['maximum']
        self.txt_status.config(text=message)
        self.txt_start_btn.config(state="normal")
        self._update_text_delete_visibility()

if __name__ == "__main__":
    if sys.platform == 'win32':
        try:
            import ctypes
            ctypes.windll.kernel32.FreeConsole()
        except Exception:
            pass
    try:
        root = tk.Tk()
        app = PhotoToolApp(root)
        root.mainloop()
    except Exception:
            logger.exception(f"__main__")
