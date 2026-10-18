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

    Реализация опирается на штатный механизм ttk: элемент ``::text``
    (экземпляр ``Treeview.Cell``) рисуется для каждой ячейки, и если у
    этого типа элементов включена однопиксельная рамка цвета границы
    (настраивается в ``ui.theme.apply_ttk_theme``), то между столбцами
    появляются ровные разделительные линии на всю высоту таблицы —
    включая шапку (через ``Treeheading.cell``).

    Никаких canvas-оверлеев поверх таблицы больше нет: раньше они
    перекрывали содержимое (было видно только линии) и обращались к
    несуществующему API (``element cget ::text -widget``), из-за чего
    приложение падало с ``AttributeError``. Плагин сводится к безопасному
    вызову перерисовки; сам он не создаёт новых окон и ничего не рисует.
    """

    def __init__(self, tree: ttk.Treeview):
        self.tree = tree

    def redraw(self):
        """Перерисовать дерево, чтобы ttk заново отрисовал рамки ячеек."""
        tree = self.tree
        try:
            if tree.winfo_exists() and tree.winfo_viewable():
                tree.item(tree, redisplay=True)
        except tk.TclError:
            pass

    def attach(self):
        """Совместимость со старым кодом: принудительная перерисовка."""
        self.redraw()

    def place_overlay(self):
        """Совместимость: оверлей больше не используется."""
        pass

    def set_known_widths(self, widths: dict):
        """Совместимость: карта ширин не нужна — линии рисует сам ttk."""
        self.redraw()

    def destroy(self):
        pass

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

    def _hide_native_scrollbar(self):
        """Убрать встроенный CTkScrollbar из разметки.

        customtkinter размещает его в сетке навсегда — полоса видна даже
        когда содержимое помещается целиком, а поверх неё фон родительской
        рамки делает её неоткликаемой. Виджет остаётся жив (на него
        ссылается внутренний API библиотеки), но исчезает из разметки.
        Вызывается и после смены corner_radius/border_width/label_text,
        потому что ``_create_grid`` возвращает полосу в сетку.
        """
        scrollbar = getattr(self, '_scrollbar', None)
        if scrollbar is not None:
            try:
                scrollbar.grid_forget()
            except Exception:
                pass

    def _create_grid(self):
        super()._create_grid()
        self._hide_native_scrollbar()

    def __init__(self, master, **kwargs):
        kwargs.setdefault('fg_color', 'transparent')
        kwargs.setdefault('label_text', '')
        super().__init__(master, **kwargs)

        # Полосы во всей сетке больше нет: ни следа от встроенного скроллбара.
        self._hide_native_scrollbar()

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
        # Ползунок прижат к правому краю панели; координаты задаются через
        # relx+anchor, а не отрицательным x — иначе полоса уходила за левый
        # край и не отвечала на клики.
        self._auto_bar.place(relx=1.0, x=-self._apply_widget_scaling(4), rely=0.5,
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
