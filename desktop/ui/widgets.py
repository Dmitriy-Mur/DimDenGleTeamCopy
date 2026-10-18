"""Вспомогательные виджеты, согласованные с темой приложения.

Содержит:
* ``AutoScrollbar``       — ttk.Scrollbar, исчезающий, когда содержимое помещается целиком;
* ``DarkTableFrame``      — панель со Treeview без лишних рамок и с автоскроллбарами;
* ``DarkScrollableFrame`` — CTkScrollableFrame с тонким ползунком прокрутки.

Названия классов сохранены для совместимости с существующим кодом UI,
но цвета берутся из текущей темы (``ui.theme``), а не зашиты как тёмные.
"""
import tkinter as tk
import tkinter.ttk as ttk

import customtkinter as ctk

from ui import theme


# ------------------------------------------------------------------ совместимость
def apply_dark_theme() -> None:
    """Устаревший алиас: настраивает ttk-стили под текущую тему."""
    theme.apply_ttk_theme()


#: Палитра по умолчанию (используется только если тема ещё не выбрана).
DARK_PANEL = theme.DARK.panel_bg
DARK_HEADER = theme.DARK.header_bg
DARK_TEXT = theme.DARK.text
DARK_BORDER = theme.DARK.border
DARK_SELECTED = theme.DARK.selected


class AutoScrollbar(ttk.Scrollbar):
    """Скроллбар, который не показывается, если всё содержимое влезает.

    Стандартный ttk.Scrollbar всегда занимает место даже при полном
    видимом содержимом. Этот класс подавляет показ ``set``, когда область
    прокрутки равна окну просмотра (first == 0, last == 1).
    """

    def set(self, lo, hi):
        if float(lo) <= 0.0 and float(hi) >= 1.0:
            # содержимое помещается целиком — прячем скроллбар
            self.forget()
            super().set(0.0, 1.0)
            return
        if not self.winfo_manager():
            self._autoshow()
        super().set(lo, hi)

    def _autoshow(self):
        """Показать скроллбар способом, которым его разместил владелец."""
        info = getattr(self, '_auto_place', None)
        if not info:
            return
        method, args, kwargs = info
        method(*args, **kwargs)


class ColumnSeparatorPlugin:
    """Вертикальные линии-разделители между столбцами Treeview.

    Рисует тонкие линии на canvas-оверлее поверх всей области таблицы
    (шапка + строки). Canvas прозрачен для событий (inputshape пусто),
    поэтому клики, выделения и сортировка по заголовкам работают как
    раньше. Линии синхронизированы с шириной колонок и прокруткой.
    """

    def __init__(self, tree: ttk.Treeview):
        self.tree = tree
        parent = tree.master
        try:
            panel_bg = theme.palette().panel_bg
        except Exception:
            panel_bg = 'gray'
        self.canvas = tk.Canvas(
            parent,
            highlightthickness=0, bd=0, bg=panel_bg,
            takefocus=0, cursor='arrow',
        )
        # Прозрачность для мыши (Tk >= 8.7): все события проходят к дереву
        # под оверлеем. На более старом Tk опции нет — тогда оверлей сам
        # прокидывает клики в дерево (_forward_click).
        self._inputshape_ok = False
        try:
            self.canvas.tk.call(self.canvas._w, 'configure', '-inputshape', '{}')  # noqa: SLF001
            self._inputshape_ok = True
        except tk.TclError:
            self.canvas.bind('<Button-1>', self._forward_click)
            self.canvas.bind('<Double-1>', self._forward_click)
        self._pending = None
        self._job_tree_configure = None
        # Запрошенные ширины колонок: ttk при stretch возвращает из
        # column(c,'width') пересчитанное значение, поэтому ведём свою
        # карту ширин через прокси метода column().
        self._req_widths = {}
        self.set_tree_column_proxy()
        # Поднимаем оверлей сразу после того, как дерево завершило свою
        # отрисовку — так линии всегда поверх ячеек и шапки.
        def _raise_overlay(_e=None):
            try:
                self.canvas.tk.call('raise', self.canvas._w)  # noqa: SLF001
            except tk.TclError:
                pass
        self.tree.bind('<Expose>', _raise_overlay, add='+')
        self.tree.bind('<Configure>', self._on_tree_configure, add='+')
        toplevel = self.tree.winfo_toplevel()
        toplevel.bind('<<ThemeChanged>>', lambda _e=None: self.redraw(), add='+')
        self.attach()

    def attach(self):
        """Разместить оверлей поверх дерева и перерисовать линии."""
        self.place_overlay()
        self.redraw()

    def place_overlay(self):
        """Совместить оверлей с геометрией дерева (в координатах родителя).

        CTkFrame рисует фон на внутреннем canvas, и winfo_x() дочерних
        ttk-виджетов возвращает координаты относительно этого canvas —
        поэтому смещение считается через разницу экранных координат.
        """
        tree = self.tree
        parent = tree.master
        x = tree.winfo_rootx() - parent.winfo_rootx()
        y = tree.winfo_rooty() - parent.winfo_rooty()
        w = max(1, tree.winfo_width())
        h = max(1, tree.winfo_height())
        try:
            self.canvas.place(x=x, y=y, width=w, height=h)
        except tk.TclError:
            pass

    def _on_tree_configure(self, event):
        """Перепозиционировать оверлей и перерисовать линии после раскладки."""
        if event.widget is not self.tree:
            return
        if self._job_tree_configure is not None:
            try:
                self.tree.after_cancel(self._job_tree_configure)
            except Exception:
                pass
        self._job_tree_configure = self.tree.after_idle(self._sync_and_redraw)

    def _sync_and_redraw(self):
        self._job_tree_configure = None
        self.place_overlay()
        self.redraw()

    def redraw(self):
        """Отложить перерисовку линий до завершения текущих событий Tk."""
        if self._pending is not None:
            try:
                self.canvas.after_cancel(self._pending)
            except Exception:
                pass
        self._pending = self.canvas.after_idle(self._draw_lines)

    def set_known_widths(self, widths: dict):
        """Запомнить заданные ширины колонок (до первого перерисовывания)."""
        for col, value in widths.items():
            try:
                self._req_widths[col] = int(value)
            except (TypeError, ValueError):
                pass
        self.redraw()


    def _column_px(self, col) -> int:
        """Фактическая ширина колонки в пикселях.

        При ``stretch=True`` ttk распределяет свободное место между
        растяжимыми колонками пропорционально их заданным ширинам;
        реальную итоговую ширину через ``tree.column(c,'width')`` получить
        нельзя (возвращает запрошенное значение), поэтому считаем её по
        формуле stretch от ширины области строк. Если строки не видны —
        берём запрошенную ширину.
        """
        tree = self.tree
        cols = tree['columns']
        # Запрошенные ширины: из карты (ставится через прокси column()) либо
        # из текущего значения колонки (до первой установки ширины).
        requested = {c: self._req_widths.get(c) or _raw_column_width(tree, c) or 120
                     for c in cols}
        children = tree.get_children()
        avail = 0
        if children:
            bb = tree.bbox(children[0])
            if bb:
                avail = bb[2]
        total_req = sum(requested.values()) or 1
        if avail > total_req + 2:
            extra = avail - total_req
            stretched = [c for c in cols if tree.column(c, 'stretch')]
            st_total = sum(requested[c] for c in stretched) or 1
            width = requested[col]
            if col in stretched and extra > 0:
                width += round(extra * requested[col] / st_total)
            return max(1, width)
        return max(1, requested[col])

    def set_tree_column_proxy(self):
        """Проксировать ``tree.column``, запоминая заданные ширины колонок.

        При ``stretch=True`` ttk возвращает из ``column(c, 'width')`` уже
        пересчитанное значение, а не запрошенное пользователем — без своей
        карты ширин разделители «съезжают» после изменения ширины колонки.
        """
        tree = self.tree
        if getattr(tree, '_sep_column_patched', False):
            return
        original = tree.column

        def column_wrapper(column=None, cnf=None, **kw):
            # Нормализуем варианты вызова: ('optname', value), ({...},), (**kw)
            opts = dict(cnf) if isinstance(cnf, dict) else {}
            if isinstance(cnf, str) and kw:
                opts.update(kw)
            elif isinstance(cnf, str):
                # чтение опции: column(col, 'width') — пробрасываем как есть
                return original(column, cnf)
            opts.update(kw)
            if 'width' in opts:
                try:
                    self._req_widths[column] = int(opts['width'])
                except (TypeError, ValueError):
                    pass
            return original(column, opts)

        tree.column = column_wrapper
        try:
            tree._sep_column_patched = True
        except AttributeError:
            pass

    def _draw_lines(self):
        self._pending = None
        canvas = self.canvas
        tree = self.tree
        if not canvas.winfo_exists() or not tree.winfo_exists():
            return
        canvas.delete('all')
        cols = tree['columns']
        if len(cols) < 2:
            return
        w = canvas.winfo_width()
        h = canvas.winfo_height()
        if w <= 1 or h <= 1:
            return
        border = theme.palette().border
        # Смещение горизонтальной прокрутки: левый край первой колонки
        # может уходить за видимую область дерева.
        offset = 0
        children = tree.get_children()
        if children:
            bbox = tree.bbox(children[0], cols[0])
            if bbox:
                offset = max(0, -bbox[0])
        # Границы колонок в координатах дерева: начало content-области плюс
        # накопленные ширины колонок минус горизонтальный скролл.
        x0 = 0
        first_bbox = tree.bbox('', cols[0]) if children else None
        if first_bbox:
            x0 = first_bbox[0] - offset
        x = x0
        for c in cols[:-1]:
            x += self._column_px(c)
            if 0 < x < w:
                canvas.create_line(x, 0, x, h, fill=border)

    def _forward_click(self, event):
        """Прокинуть клик из оверлея в дерево (fallback для Tk < 8.7).

        Определяет элемент под курсором: на шапке — выполняет heading
        command (сортировка), на строке — выделяет её.
        """
        tree = self.tree
        tx = event.x + self.canvas.winfo_x() - tree.winfo_x()
        ty = event.y + self.canvas.winfo_y() - tree.winfo_y()
        item = tree.identify_row(ty)
        if not item and tree.identify_region(tx, ty) == 'heading':
            col = tree.identify_column(tx)
            if col and col != '#0':
                try:
                    index = int(col[1:]) - 1
                    cmd = tree.heading(tree['columns'][index], 'command')
                    if cmd:
                        tree.tk.eval(cmd)
                except (ValueError, IndexError, tk.TclError):
                    pass
            return 'break'
        if item:
            tree.selection_set(item)
            tree.focus(item)
        return 'break'

    def destroy(self):
        try:
            self.canvas.destroy()
        except tk.TclError:
            pass



def _raw_column_width(tree, col):
    """Реальное значение опции width колонки, минуя прокси-обёртку."""
    try:
        return int(tree.tk.call(tree._w, 'column', col, '-width'))  # noqa: SLF001
    except (tk.TclError, ValueError):
        return None

class DarkTableFrame(ctk.CTkFrame):
    """Панель со Treeview и скроллбарами, исчезающими без необходимости.

    * фон панели берётся из текущей темы;
    * рамок нет: панель отличима фоном, разграничителями служат только
      шапка таблицы и тонкие разделители колонок;
    * вертикальный скроллбар появляется только если строк больше, чем видно;
    * горизонтальный — только если колонки не влезают по ширине;
    * над таблицей нет «выпирающих» полос: разделители рисуются поверх
      самой таблицы через ``ColumnSeparatorPlugin``;
    * при смене темы (событие ``<<ThemeChanged>>``) перекрашивается сам.
    """

    def __init__(self, master, columns=None, headings=None, column_widths=None,
                 **kwargs):
        kwargs.setdefault('fg_color', 'transparent')
        kwargs.setdefault('corner_radius', 8)
        super().__init__(master, **kwargs)

        pal = theme.palette()
        self.configure(fg_color=pal.panel_bg)

        self.tree = ttk.Treeview(
            self,
            columns=tuple(columns or ()),
            show='headings',
            style='App.Treeview',
            selectmode='browse',
        )

        # переменная позиции горизонтальной прокрутки (отслеживается снаружи)
        self.xview_var = tk.StringVar()

        self._vbar = AutoScrollbar(self, orient='vertical',
                                   style='App.Vertical.TScrollbar',
                                   command=self.tree.yview)
        self._hbar = AutoScrollbar(self, orient='horizontal',
                                   style='App.Horizontal.TScrollbar',
                                   command=self._xview_command)
        self.tree.configure(yscrollcommand=self._vbar.set, xscrollcommand=self._xset)

        self._vbar._auto_place = (self._vbar.pack, (), {'side': 'right', 'fill': 'y'})
        self._hbar._auto_place = (self._hbar.pack, (), {'side': 'bottom', 'fill': 'x'})

        # Порядок pack важен: сначала полосы скроллов по краям, затем Treeview.
        self._vbar.pack(side='right', fill='y')
        self._hbar.pack(side='bottom', fill='x')
        self.tree.pack(side='left', fill='both', expand=True)

        for col in (columns or ()):
            width = (column_widths or {}).get(col, 120)
            text = (headings or {}).get(col, col)
            self.tree.heading(col, text=text, anchor='w')
            self.tree.column(col, width=width, minwidth=60, anchor='w', stretch=True)

        # Разделители между столбцами: прозрачный canvas-оверлей поверх всей
        # таблицы (не над ней — никаких «выпирающих» полос), синхронный с
        # ширинами колонок и прокруткой. Создаётся до строковых тегов, но
        # после настройки колонок, чтобы карта ширин была полной.
        self._sep_plugin = ColumnSeparatorPlugin(self.tree)
        self._sep_plugin.set_known_widths({c: (column_widths or {}).get(c, 120)
                                           for c in (columns or ())})

        # Чередование строк для читаемости
        self.tree.tag_configure('oddrow', background=pal.row_alt)
        self.tree.tag_configure('evenrow', background=pal.panel_bg)
        self._row_count = 0

        # Перекраска при переключении темы.
        toplevel = self.winfo_toplevel()
        toplevel.bind('<<ThemeChanged>>', lambda _e=None: self._on_theme_change(), add='+')

    # ------------------------------------------------------------------ theme
    def _on_theme_change(self):
        pal = theme.palette()
        self.configure(fg_color=pal.panel_bg)
        plugin = getattr(self, '_sep_plugin', None)
        if plugin is not None and plugin.canvas.winfo_exists():
            # фон оверлея совпадает с фоном панели: под шапкойTreeview он
            # не виден, а в щели между деревом и скроллбаром не «светится»
            plugin.canvas.configure(bg=pal.panel_bg)
        self.tree.tag_configure('oddrow', background=pal.row_alt)
        self.tree.tag_configure('evenrow', background=pal.panel_bg)
        self.refresh_column_separators()

    # ------------------------------------------------------------- separators
    def refresh_column_separators(self):
        """Перерисовать вертикальные разделители между колонками Treeview."""
        plugin = getattr(self, '_sep_plugin', None)
        if plugin is not None:
            plugin.redraw()

    def _xview_command(self, *args):
        self.tree.xview(*args)
        self._sync_xview_var()

    def _xset(self, lo, hi):
        self._hbar.set(lo, hi)
        self.xview_var.set(f'{lo} {hi}')
        self.refresh_column_separators()

    def _sync_xview_var(self):
        lo, hi = self.tree.xview()
        self.xview_var.set(f'{lo} {hi}')

    def clear(self):
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        self._row_count = 0


class DarkScrollableFrame(ctk.CTkScrollableFrame):
    """CTkScrollableFrame с ползунком прокрутки, скрытым когда он не нужен.

    Встроенный CTkScrollbar всегда занимает место справа; здесь он заменяется
    на собственный canvas-скроллбар, который рисуется только при реальной
    необходимости (содержимое выше области просмотра). Цвета обновляются
    при смене темы.
    """

    BAR_WIDTH = 12
    BAR_TROUGH = 'transparent'

    def __init__(self, master, **kwargs):
        kwargs.setdefault('fg_color', 'transparent')
        kwargs.setdefault('label_text', '')
        super().__init__(master, **kwargs)

        # Родительский CTkFrame перерисовывает свой canvas при любом
        # изменении размера — после этого перерисуем и наш скроллбар,
        # чтобы он не оказался под фоном рамки.
        parent_canvas = self._parent_frame._canvas
        parent_canvas.bind('<Configure>', lambda e: self._schedule_redraw(), add=True)

        self._auto_bar = tk.Canvas(
            self._parent_frame,
            width=self._apply_widget_scaling(self.BAR_WIDTH),
            height=1,
            highlightthickness=0,
            bd=0,
            bg=self._canvas_bg(),
        )
        self._auto_bar.place(x=-self._apply_widget_scaling(self.BAR_WIDTH + 6), rely=0.5,
                             anchor='e', relheight=0.94)
        self._auto_bar.bind('<Button-1>', self._bar_clicked)
        self._auto_bar.bind('<B1-Motion>', self._bar_drag)

        self._parent_canvas.configure(yscrollcommand=self._auto_set)
        self._parent_canvas.bind('<Configure>', lambda e: self._schedule_redraw(), add=True)

        self._thumb_start = 0.0
        self._thumb_end = 1.0
        self._drag_offset = 0.0
        self._redraw_job = None

        toplevel = self.winfo_toplevel()
        toplevel.bind('<<ThemeChanged>>', lambda _e=None: self._schedule_redraw(), add='+')

    def _bar_color(self) -> str:
        return theme.palette().scrollbar

    def _canvas_bg(self) -> str:
        fg = self._parent_frame.cget('fg_color')
        color = self._parent_frame.cget('bg_color') if fg == 'transparent' else fg
        return self._apply_appearance_mode(color)

    # -- синхронизация с канвасом -------------------------------------------
    def _auto_set(self, lo, hi):
        self._thumb_start = float(lo)
        self._thumb_end = float(hi)
        self._schedule_redraw()

    def _schedule_redraw(self):
        """Перерисовать ползунок после завершения текущих событий Tk."""
        if self._redraw_job is not None:
            try:
                self.winfo_toplevel().after_cancel(self._redraw_job)
            except Exception:
                pass
        try:
            self._redraw_job = self.winfo_toplevel().after_idle(self._redraw_bar)
        except Exception:
            self._redraw_bar()

    def _after_content_change(self):
        """Обновить scrollregion и видимость скроллбара после изменения содержимого."""
        self._parent_canvas.update_idletasks()
        bbox = self._parent_canvas.bbox('all')
        if bbox:
            self._parent_canvas.configure(scrollregion=bbox)
        self._redraw_bar()

    @property
    def _needs_scroll(self) -> bool:
        region = self._parent_canvas.bbox('all')
        if not region:
            return False
        content_h = region[3] - region[1]
        return content_h > self._parent_canvas.winfo_height() + 1

    def _redraw_bar(self):
        self._redraw_job = None
        if not self._auto_bar.winfo_exists():
            return
        self._auto_bar.configure(bg=self._canvas_bg())
        self._auto_bar.delete('all')
        if not self._needs_scroll:
            return
        h = self._auto_bar.winfo_height()
        w = self._auto_bar.winfo_width()
        if h <= 1 or w <= 1:
            return
        top = max(0, int(self._thumb_start * h))
        bottom = min(h, int(self._thumb_end * h))
        if bottom - top < 20:
            bottom = min(h, top + 20)
        pad = 2
        try:
            self._auto_bar.create_rectangle(pad, top, w - pad, bottom, radius=4,
                                            fill=self._bar_color(), outline='')
        except tk.TclError:
            # Tk < 8.7 не поддерживает сглаженные углы у прямоугольников
            self._auto_bar.create_rectangle(pad, top, w - pad, bottom,
                                            fill=self._bar_color(), outline='')

    # -- взаимодействие -------------------------------------------------------
    def _value_from_y(self, y):
        h = max(1, self._auto_bar.winfo_height())
        length = self._thumb_end - self._thumb_start
        center = min(max(y / h, length / 2), 1 - length / 2)
        start = center - length / 2
        self._parent_canvas.yview_moveto(start)

    def _bar_clicked(self, event):
        h = max(1, self._auto_bar.winfo_height())
        self._drag_offset = ((self._thumb_start + self._thumb_end) / 2) - event.y / h
        self._value_from_y(event.y)

    def _bar_drag(self, event):
        h = max(1, self._auto_bar.winfo_height())
        self._value_from_y(event.y + self._drag_offset * h)
