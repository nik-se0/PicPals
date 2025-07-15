import os
import sys
import shutil
import ctypes
import time
import textwrap
from PIL import Image
import imagehash
import numpy as np
import cv2
import win32com.client
import colorama
import scipy._cyutility
from collections import defaultdict
from PIL import ExifTags

sys.stdout = colorama.AnsiToWin32(sys.stdout).stream

colorama.init()
MAGENTA = "\033[38;2;255;138;177m"
RESET   = colorama.Style.RESET_ALL

METHODS_DATA = {
    '1': {
        "rus": "Average Hash",
        "desc": "Cравнивает каждый пиксель со средней яркостью всех пикселей.",
        "size": "8×8",
        "mode": "ЧБ",
        "func": imagehash.average_hash
    },
    '2': {
        "rus": "RGB Average Hash",
        "desc": "Вычисляет средней яркостью для R, G и B по-отдельности и объединяет три результата в один вектор.",
        "size": "8×8×3",
        "mode": "Цвет",
        "func": None
    },
    '3': {
        "rus": "Difference Hash",
        "desc": "Сравнивает яркость соседних пикселей в строках.",
        "size": "9×8",
        "mode": "ЧБ",
        "func": imagehash.dhash
    },
    '4': {
        "rus": "Perceptual Hash",
        "desc": "Преобразует пространственные данные в частотную область и сравнивает среднюю амплитуду колебаний низких частот (без шумов и деталей)",
        "size": "32×32",
        "mode": "ЧБ",
        "func": imagehash.phash
    },
    '5': {
        "rus": "RGB Perceptual Hash",
        "desc": "Запускает Perceptual Hash для каждого из каналов R, G и B и объединяет их в итоговый вектор.",
        "size": "32×32×3",
        "mode": "Цвет",
        "func": None
    },
    '6': {
        "rus": "Wavelet Hash",
        "desc": "С помощью функции Хаара, изобраджение раскладывается на две части: грубую картинку и мелкие детали. Из всех полученных коэффициентов выбираются только приближённые, для сравнения со средним значением (медианой)",
        "size": "—",
        "mode": "ЧБ",
        "func": imagehash.whash
    },
    '7': {
        "rus": "HSV Color Hash",
        "desc": "Преобразует в HSV, строит 3D-гистограмму по H, S, V.",
        "size": "bins³",
        "mode": "Цвет",
        "func": None
    },
    '8': {
        "rus": "RGB Histogram Hash",
        "desc": "Квантизирует RGB-каналы, строит 3D-гистограмму.",
        "size": "bins³",
        "mode": "Цвет",
        "func": None
    },
    '9': {
        "rus": "Lab Histogram Hash",
        "desc": "Переводит в Lab, создаёт 3D-гистограмму .",
        "size": "bins³",
        "mode": "Цвет",
        "func": None
    },
    '10': {
        "rus": "Spatial Grid Hash",
        "desc": "Делит изображение на 4×4 блока, строит RGB-гистограммы блоков.",
        "size": "4×4×bins³",
        "mode": "Цвет",
        "func": None
    },
}

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
def lab_hist_hash(img, bins=8):
    bgr = cv2.cvtColor(np.array(img.convert('RGB'))[..., ::-1], cv2.COLOR_BGR2LAB)
    arr = bgr.reshape(-1,3)
    hist, _ = np.histogramdd(arr, bins=(bins,)*3, range=((0,255),)*3)
    flat = hist.flatten(); m = np.median(flat)
    return (flat > m).astype(int)
def spatial_grid_color_hash(img, grid_x=4, grid_y=4, bins=8):
    arr = np.array(img.convert('RGB'))
    h, w = arr.shape[:2]
    by, bx = h//grid_y, w//grid_x
    bits = []
    for i in range(grid_y):
        for j in range(grid_x):
            block = arr[i*by:(i+1)*by, j*bx:(j+1)*bx]
            hist, _ = np.histogramdd(block.reshape(-1,3),
                                     bins=(bins,)*3, range=((0,255),)*3)
            flat = hist.flatten(); m = np.median(flat)
            bits.append((flat > m).astype(int))
    return np.concatenate(bits)
# Привязка функций
METHODS_DATA['2']['func']  = hsv_color_hash
METHODS_DATA['5']['func']  = rgb_avg_hash
METHODS_DATA['7']['func']  = rgb_phash
METHODS_DATA['8']['func']  = rgb_hist_hash
METHODS_DATA['9']['func']  = lab_hist_hash
METHODS_DATA['10']['func'] = spatial_grid_color_hash


def maximize_console():
    if os.name == 'nt':
        kd = ctypes.windll.kernel32; ud = ctypes.windll.user32
        hwnd = kd.GetConsoleWindow()
        if hwnd: ud.ShowWindow(hwnd, 3)

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def create_unique_folder(base_path, folder_name):
    result_path = os.path.join(base_path, folder_name)
    counter = 1
    while os.path.exists(result_path):
        result_path = os.path.join(base_path, f"{folder_name} ({counter})")
        counter += 1
    os.makedirs(result_path)
    return result_path
def choose_folder():        #Выбор папки
    print("Введите путь к папке с фотографиями:")
    inp = input(MAGENTA + "> ").strip()
    print(RESET, end='')
    folder = inp or os.getcwd()
    if not os.path.isdir(folder):
        print("Папка не найдена, повторите.")
        return choose_folder()
    return folder
def choose_threshold():     #Выбор процент схожести
    print("\nВведите минимальный процент сходства (0–100):")
    inp = input(MAGENTA + "> ").strip()
    print(RESET, end='')
    try:
        val = float(inp)
        if not (0 <= val <= 100): raise ValueError
        return val
    except:
        print("Ошибка ввода, повторите.")
        return choose_threshold()
def choose_method():        #Выбор метода
    print("\nДоступные методы фильтрации:")
    print("| №  | Название                            | Описание                                    | Размер    | Цвет/ЧБ |")
    print("|----|-------------------------------------|---------------------------------------------|-----------|---------|")
    for k, info in METHODS_DATA.items():
        size_disp = info['size']
        lines = textwrap.wrap(info['desc'], width=43)
        for i, line in enumerate(lines):
            if i == 0:
                print(f"| {k:<2} | {info['rus']:<35} | {line:<43} | {size_disp:<9} | {info['mode']:<7} |")
            else:
                print(f"|    | {'':35} | {line:<43} | {'':9} | {'':7} |")
    print("|----|-------------------------------------|---------------------------------------------|-----------|---------|\n 0. Вернуться назад")
    choice = input(MAGENTA + "> ").strip()
    print(RESET, end='')
    if choice == '0':
        return None
    if choice not in METHODS_DATA:
        print("Неверный номер, повторите.")
        return choose_method()
    return METHODS_DATA[choice]['func']
def choose_action():        #Выбор скачивается/ярлыки
    print("\nЧто делать с найденными фотографиями?")
    print(" 1. Создать ярлыки")
    print(" 2. Копировать файлы")
    print(" 0. Вернуться назад")
    c = input(MAGENTA + "> ").strip()
    print(RESET, end='')
    if c == '0':
        return None
    if c not in ('1', '2'):
        clear_screen()
        print("Неверный выбор, повторите.")
        return choose_action()
    return c

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
        sc.IconLocation     = src
        sc.save()
        return True
    except:
        safe_copy(src, dst)
        return False
def draw_progress_bar(current, total, up_lines=2, f=0):      #Отрисовка прогресс-бара розового цвета.
    width     = shutil.get_terminal_size((80, 20)).columns
    bar_length = max(10, int(width * 0.5))
    pct        = current / total
    filled_len = int(bar_length * pct)
    count_str = f"{current}/{total}"
    bar_str   = MAGENTA + '█' * filled_len + '-' * (bar_length - filled_len) + RESET
    pct_str   = f"{pct * 100:6.2f}%"
    bar_line  = f"{bar_str} {pct_str}"
    pad_count = max(0, (width - len(count_str)) // 2)
    pad_bar   = max(0, (width - len(bar_line))   // 2)

    # теперь смотрим флаг
    if current > 1:
        sys.stdout.write('\033[F' * up_lines)

    if f!=3:
        sys.stdout.write(' ' * pad_count + count_str + '\n')
    else:
         sys.stdout.write(' ' * pad_count + "" + '\n')
    sys.stdout.write(' ' * pad_bar   + bar_line  + '\n')
    sys.stdout.flush()
def print_summary_table(elapsed, proc, total, groups, singles,action, succ, fail, result):
    headers = ["Время работы","Обработано","Создано групп","Фотографий вне групп"]
    values = [f"{elapsed:.1f} сек",f"{proc}/{total}",str(groups),str(singles)]
    if action == '1':
        headers += ["Ярлыков создано", "Копий вместо ярлыков"]
        values  += [str(succ), str(fail)]
    headers.append("Результаты в")
    values.append(result)
    col_widths = [max(len(h), len(v))for h, v in zip(headers, values)]
    sep = "+" + "+".join("-" * (w + 2) for w in col_widths) + "+"
    print(sep)
    header_row = "|" + "|".join(f" {h.center(w)} " for h, w in zip(headers, col_widths)) + "|"
    print(header_row)
    print(sep)
    value_row = "|" + "|".join(f" {v.ljust(w)} " for v, w in zip(values, col_widths)) + "|"
    print(value_row)
    print(sep)

remove_last_folder = lambda p: os.path.dirname(os.path.normpath(p))

def resolve_shortcut(path):
    try:
        from win32com.client import Dispatch
    except ImportError:
        return path
    shell = Dispatch('WScript.Shell')
    shortcut = shell.CreateShortCut(path)
    return shortcut.Targetpath or path
def delete_duplicates(root_folder):
    print("\nВыберите режим удаления оригиналов ярлыков:")
    print(" 1 — удалить оригиналы всех ярлыков")
    print(" 2 — оставить один оригинал в каждой группе, удалить остальные")
    while True:
        mode = input("> ").strip()
        if mode in ('1', '2'):
            break
        print("Неверный выбор, введите 1 или 2.")

    group_links = {}
    for entry in os.scandir(root_folder):
        if not entry.is_dir() or not entry.name.startswith("Группа_"):
            continue
        links = sorted(
            os.path.join(entry.path, fn)
            for fn in os.listdir(entry.path)
            if fn.lower().endswith('.lnk')
        )
        if links:
            group_links[entry.path] = links

    if not group_links:
        print("\nНет папок 'Группа_*' или ярлыков для обработки.\n")
        return

    tasks = []
    for links in group_links.values():
        if mode == '1':
            tasks.extend(links)
        else: 
            tasks.extend(links[1:])
    total = len(tasks)
    if total == 0:
        print("\nНет дубликатов для удаления в выбранном режиме.\n")
        return
    removed_origins = 0
    removed_links = 0
    print(f"\nУдаление начато, всего задач: {total}\n")
    for idx, lnk in enumerate(tasks, start=1):
        target = resolve_shortcut(lnk)
        if os.path.isfile(target):
            try:
                os.remove(target)
                removed_origins += 1
            except OSError:
                pass
        try:
            os.remove(lnk)
            removed_links += 1
        except OSError:
            pass
        draw_progress_bar(idx, total, up_lines=2, f=0)

    print(f"Удалено ярлыков:  {removed_links}\n")

def filter_folder(n, src='', method=None, threshold=None):
    if src == "":
        src = choose_folder()

    # Выбор метода, порога и действия, если не рекурсивная итерация
    if n != 3:
        method = choose_method()
        if method is None:
            return None
        threshold = choose_threshold()
        action = choose_action()
        if action is None:
            return src
        flag = 1
    else:
        # при рекурсивном проходе копируем файлы
        action = '2'
        flag = 0

    # Собираем все изображения и ярлыки из папки и всех её подпапок
    all_files = []
    for root, _, filenames in os.walk(src):
        for f in filenames:
            full_path = os.path.join(root, f)
            if os.path.isfile(full_path) and (is_image_file(f) or f.lower().endswith('.lnk')):
                all_files.append(full_path)
    total = len(all_files)

    # Создаём результирующую папку при первом прогоне
    if flag == 1:
        result = create_unique_folder(src, "Результат фильтрации")
        print(f"\nФильтрация начата, всего фотографий (с учётом подпапок): {total}\n")
    else:
        result = src

    os.makedirs(result, exist_ok=True)

    start       = time.time()
    proc        = 0
    clusters    = []
    group_count = 0
    succ = fail = 0

    # Основной цикл по всем найденным файлам
    for path in all_files:
        proc += 1
        fname = os.path.basename(path)

        # Если это ярлык в рекурсивном режиме — разрешаем его
        if n == 3 and fname.lower().endswith('.lnk'):
            real = resolve_shortcut(path)
            compare_path = real if os.path.exists(real) and is_image_file(real) else path
        else:
            compare_path = path

        # Открываем изображение и приводим к RGB/RGBA
        try:
            with Image.open(compare_path) as img:
                if img.mode == 'P':
                    img = img.convert('RGBA')
                elif img.mode not in ('RGB', 'RGBA'):
                    img = img.convert('RGB')

                hsh = method(img)
                bits = hsh.hash.flatten() if hasattr(hsh, 'hash') else hsh.flatten()
        except Exception as e:
            print(f"[ERROR] {method.__name__} упал на {compare_path!r}: {e}")
            continue

        # Попытка добавить в существующую группу
        placed = False
        for cl in clusters:
            dist = (bits != cl['bits']).sum()
            sim  = (1 - dist / len(bits)) * 100
            if sim >= threshold:
                placed = True
                cl['count'] += 1

                # При создании второй фотографии — создаём папку группы
                if cl['count'] == 2:
                    group_count += 1
                    grp = os.path.join(result, f"Группа_{group_count}")
                    os.makedirs(grp, exist_ok=True)
                    cl['group_dir'] = grp

                    # первую фотографию помещаем в группу
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

        # Если не попало ни в одну группу — создаём новую
        if not placed:
            clusters.append({
                'bits'      : bits,
                'count'     : 1,
                'first_path': path,
                'group_dir' : None
            })

        # Обновляем прогресс-бар
        draw_progress_bar(proc, total, up_lines=2, f=n)

    # Копируем «одиночки» в отдельную папку, если мы копируем, а не делаем ярлыки
    if action != '1':
        others = os.path.join(result, "Остальные")
        os.makedirs(others, exist_ok=True)
        for cl in clusters:
            if cl['count'] == 1:
                safe_copy(cl['first_path'], others)

    # При рекурсивном проходе удаляем исходные ярлыки
    if n == 3:
        for path in all_files:
            if path.lower().endswith('.lnk'):
                try:
                    os.remove(path)
                except OSError:
                    pass

    # Вычисляем статистику и выводим итоговую таблицу
    elapsed = time.time() - start
    groups  = sum(1 for c in clusters if c['count'] > 1)
    singles = sum(1 for c in clusters if c['count'] == 1)

    if flag == 1:
        print_summary_table(
            elapsed=elapsed, proc=proc, total=total,
            groups=groups, singles=singles,
            action=action, succ=succ, fail=fail,
            result=result
        )

    return result


def choose_task():
    print("\nВыберите задачу:")
    print(" 1 — Фильтрация похожих изображений")
    print(" 2 — Группировка фотографий по дате")
    print(" 3 — Удаление размытых фотографий")
    print(" 4 — Поиск документов/скриншотов/фотографий текста")
    print(" 0 — Выход")
    c = input(MAGENTA + "> ").strip()
    print(RESET, end='')
    return c

def group_photos_by_date(src):
    print("\nГруппировка по дате:")
    print(" 1 — по годам")
    print(" 2 — по годам и месяцам")
    print(" 3 — по годам, месяцам и дням")
    lvl = input(MAGENTA + "> ").strip()
    print(RESET, end='')
    if lvl not in ('1','2','3'):
        print("Неверный выбор, повторите.")
        return group_photos_by_date(src)

    # читаем EXIF-дату, если нет — берём mtime
    def get_date(path):
        try:
            img = Image.open(path)
            info = {ExifTags.TAGS[k]: v for k,v in img._getexif().items() if k in ExifTags.TAGS}
            dt = info.get('DateTimeOriginal', None)
            if dt:
                Y,M,D = dt.split()[0].split(':')
                return Y, M, D
        except:
            pass
        st = os.stat(path).st_mtime
        tm = time.localtime(st)
        return str(tm.tm_year), f"{tm.tm_mon:02d}", f"{tm.tm_mday:02d}"

    files = [os.path.join(root, f)
             for root,_,files in os.walk(src)
             for f in files if is_image_file(f)]
    for path in files:
        Y,M,D = get_date(path)
        if lvl == '1':
            target = os.path.join(src, Y)
        elif lvl == '2':
            target = os.path.join(src, Y, M)
        else:
            target = os.path.join(src, Y, M, D)
        safe_copy(path, target)
    print(f"\nГруппировка завершена, папки созданы в {src}")

def delete_blurred_photos(src, thresh=100.0):
    print("\nУдаление размытых фотографий (Variance of Laplacian < threshold)")
    print("Введите порог резкости (рекомендуем 100–300):")
    inp = input(MAGENTA + "> ").strip(); print(RESET, end='')
    try:
        thresh = float(inp)
    except:
        print("Неверный ввод, используем 100.0.")
        thresh = 100.0

    removed = 0
    files = [os.path.join(root,f)
             for root,_,files in os.walk(src)
             for f in files if is_image_file(f)]
    total = len(files)
    for i, path in enumerate(files, 1):
        img = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
        score = cv2.Laplacian(img, cv2.CV_64F).var()
        if score < thresh:
            os.remove(path)
            removed += 1
        draw_progress_bar(i, total, up_lines=2, f=0)
    print(f"\nУдалено размытых: {removed} из {total}")

def find_text_images(src):
    print("\nПоиск изображений с текстом (OCR)…")
    out = create_unique_folder(src, "Документы_и_текст")
    found = 0
    files = [os.path.join(root,f)
             for root,_,files in os.walk(src)
             for f in files if is_image_file(f)]
    total = len(files)
    for i, path in enumerate(files, 1):
        text = pytesseract.image_to_string(path, lang='rus+eng').strip()
        if len(text) > 20:
            safe_copy(path, out)
            found += 1
        draw_progress_bar(i, total, up_lines=2, f=0)
    print(f"\nНайдено изображений с текстом: {found}")

# --- Изменение main() ---
def main():
    maximize_console()
    clear_screen()
    while True:
        choice = choose_task()
        if choice == '0':
            sys.exit(0)
        src = choose_folder()
        clear_screen()

        if choice == '1':
            filter_folder(1, src)
        elif choice == '2':
            group_photos_by_date(src)
        elif choice == '3':
            delete_blurred_photos(src)
        elif choice == '4':
            find_text_images(src)
        else:
            print("Неверный выбор, повторите.")
        print("\nОперация завершена.\n")





def main():
    maximize_console()
    clear_screen()
    while True:
        result = filter_folder(1)
        src = remove_last_folder(result)
        if result is None:
            clear_screen()
            continue

        while True:
            has_result_dir = 'Результат фильтрации' in result
            if has_result_dir:
                print("\nЧто дальше?")
                print(" 1 — Заново для этой же папки")
                print(" 2 — Заново для новой папки")
                print(" 3 — Рекурсивно для всех подпапок")
                print(" 4 — Удалить оригиналы ярлыков (с выбором режима)")
                print(" 0 — Выход")
                choice = input("> ").strip()
                clear_screen()
            else:
                clear_screen()
                choice = '1'
                src = result

            if choice == '0':
                sys.exit(0)
            if choice == '1':
                print(f"\nФильтрация для папки {src}\n")
                res2 = filter_folder(2, src)
                if res2 is not None:
                    result = res2
                continue
            if choice == '2':
                break
            if choice == '3':
                print(f"\nРекурсивная фильтрация папки: {result}\n")
                method = choose_method()
                if method is None:
                    break
                threshold = choose_threshold()
                subfolders = [
                    d for d in os.listdir(result)
                    if os.path.isdir(os.path.join(result, d))
                ]
                total = len(subfolders)
                for i, folder_name in enumerate(subfolders, start=1):
                    draw_progress_bar(i, total, 4)
                    folder_path = os.path.join(result, folder_name)
                    filter_folder(3, folder_path, method, threshold)
                continue
            if choice == '4':
                delete_duplicates(result)
                print("Дублирующие ярлыки и их оригиналы удалены.")
                continue

            print("Некорректный ввод. Попробуйте еще раз.")
        clear_screen()

if __name__ == "__main__":
    try:
        if getattr(sys, "frozen", False): # переключаем cwd из %TEMP% в папку с exe
            os.chdir(os.path.dirname(sys.executable))
        #print(f"[DEBUG] Текущая рабочая папка: {os.getcwd()}")
        main()
    except Exception:
        import traceback
        traceback.print_exc()
        input("Произошла ошибка. Нажмите Enter для выхода...")