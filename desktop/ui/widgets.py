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


def _to_hex(color) -> str:
    """Привести цвет Tk к hex-строке (поддержка 'gray55' и вида для двух тем)."""
    if isinstance(color, (tuple, list)):
        color = color[0]
    s = str(color).strip()
    if s.lower() == 'transparent':
        return '#000000'
    if s.startswith('#'):
        if len(s) == 4:  # сокращённая форма #abc
            return '#' + ''.join(ch * 2 for ch in s[1:])
        return s
    try:
        import tkinter as _tk
        root = _tk._default_root
        if root is not None:
            rgb = root.winfo_rgb(s)  # значения 0..65535
            return '#{r:02x}{g:02x}{b:02x}'.format(r=rgb[0] // 256,
                                                   g=rgb[1] // 256,
                                                   b=rgb[2] // 256)
    except Exception:
        pass
    return '#808080'


def _mix_colors(c1: str, c2: str, t: float) -> str:
    """Линейная смесь двух цветов: t=0 → c1, t=1 → c2."""
    def comp(h):
        h = _to_hex(h).lstrip('#')
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    a, b = comp(c1), comp(c2)
    r = tuple(round(x + (y - x) * t) for x, y in zip(a, b))
    return f'#{r[0]:02x}{r[1]:02x}{r[2]:02x}'


class DarkScrollableFrame(ctk.CTkScrollableFrame):
    """CTkScrollableFrame с тонкой полосой прокрутки справа от содержимого.

    Исправляет два дефекта предыдущих реализаций:

    1. *Наложение на элементы дерева.* Собственный canvas-ползунок
       размещался через ``place`` поверх холста с содержимым и перекрывал
       строки дерева. Теперь полоса — это нативный ``CTkScrollbar``,
       размеченный в отдельной grid-колонке справа от ``_parent_canvas``:
       физически пересечься с узлами он не может.
    2. *Слияние с фоном.* Нативная полоса customtkinter по умолчанию
       красится в цвета темы библиотеки, близкие к фону панели. Здесь
       ползунок перекрашивается в контрастный оттенок палитры приложения
       (``pal.scrollbar``), «корыто» — в чуть затемнённый фон панели,
       так что полоса различима и в светлой, и в тёмной теме; при
       наведении ползунок подсвечивается.

    Когда содержимое помещается целиком, полоса становится полностью
    прозрачной (визуально исчезает, ширина контента при этом не «прыгает»,
    т.к. weight у колонки полосы нулевой).
    """

    #: Ширина колонки прокрутки (в масштабируемых единицах UI).
    BAR_WIDTH = 10

    def __init__(self, master, **kwargs):
        kwargs.setdefault('fg_color', 'transparent')
        kwargs.setdefault('label_text', '')
        super().__init__(master, **kwargs)

        # Наследие прежней реализации: canvas-оверлей поверх содержимого.
        # Убираем, если он вдруг существует (пересборка виджета на лету).
        old_bar = getattr(self, '_auto_bar', None)
        if old_bar is not None:
            try:
                old_bar.destroy()
            except tk.TclError:
                pass
        self._auto_bar = None

        self._thumb_start = 0.0
        self._thumb_end = 1.0
        self._redraw_job = None

        # Колонка полосы: фиксированная ширина, нулевой weight — содержимое
        # всегда в column 0 и полоса его не перекрывает.
        self._apply_scrollbar_column()

        # Перекраска при любых изменениях геометрии и при смене темы.
        for cv in (self._parent_frame._canvas, self._parent_canvas):
            cv.bind('<Configure>', lambda e: self._schedule_redraw(), add=True)
        self.bind('<Configure>', lambda e: self._schedule_redraw(), add=True)

        # Прокрутка колесом/сменой содержимого тоже должна обновлять
        # состояние «видима/прозрачна» и положение ползунка.
        self._parent_canvas.configure(yscrollcommand=self._auto_set)

        toplevel = self.winfo_toplevel()
        toplevel.bind('<<ThemeChanged>>', lambda _e=None: self._schedule_redraw(), add='+')

        self._schedule_redraw()

    # ------------------------------------------------------------------ layout
    def _apply_scrollbar_column(self):
        """Задать параметры grid для колонки прокрутки."""
        try:
            pf = self._parent_frame
            pf.grid_columnconfigure(0, weight=1, minsize=0)
            pf.grid_columnconfigure(1, weight=0,
                                    minsize=self._apply_widget_scaling(self.BAR_WIDTH))
        except Exception:
            pass

    def _create_grid(self):
        super()._create_grid()
        # После перестроения сетки (corner_radius / border_width / label_text)
        # заново настроить колонку полосы.
        if hasattr(self, '_parent_frame'):
            self._apply_scrollbar_column()

    # ------------------------------------------------------------------- цвета
    def _bar_color(self) -> str:
        """Контрастный цвет ползунка для текущей темы."""
        return theme.palette().scrollbar

    def _panel_base_color(self) -> str:
        fg = self._parent_frame.cget('fg_color')
        color = self._parent_frame.cget('bg_color') if fg == 'transparent' else fg
        base = self._apply_appearance_mode(color)
        if isinstance(base, (tuple, list)):
            base = base[0]
        return str(base)

    def _trough_color(self) -> str:
        """«Корыто» — чуть темнее фона панели, чтобы полоса читалась."""
        base = self._panel_base_color()
        factor = 0.18 if theme.current_mode() == 'dark' else 0.08
        return _mix_colors(base, '#000000', factor)

    def _hover_color(self) -> str:
        """Подсветка ползунка при наведении — ярче основного оттенка."""
        pal = theme.palette()
        base = pal.scrollbar
        target = '#ffffff' if theme.current_mode() == 'dark' else '#000000'
        return _mix_colors(base, target, 0.25)

    def _recolor_scrollbar(self):
        """Перекрасить нативный CTkScrollbar под тему и нужность прокрутки.

        Без необходимости прокрутки все элементы полосы прозрачны — она
        визуально исчезает, но продолжает занимать свою колонку (ширина
        контента не меняется). При необходимости — контрастный ползунок
        над нейтральным корытом; цвета берутся из палитры приложения, а
        не из темы customtkinter, поэтому полоса не сливается с фоном ни
        в светлой, ни в тёмной теме.
        """
        sb = getattr(self, '_scrollbar', None)
        if sb is None or not sb.winfo_exists():
            return
        needs = self._needs_scroll
        trough = self._trough_color() if needs else 'transparent'
        thumb = self._bar_color() if needs else 'transparent'
        hover = self._hover_color() if needs else 'transparent'
        try:
            sb.configure(fg_color=trough, button_color=thumb, button_hover_color=hover)
        except Exception:
            pass
        # configure мог быть перехвачен внутренними обработчиками библиотеки —
        # проверяем результат и правим приватные атрибуты напрямую, после чего
        # заставляем полосу перерисоваться.
        cur_btn = str(sb.cget('button_color'))
        if cur_btn != thumb:
            try:
                sb._fg_color = trough
                sb._button_color = thumb
                sb._button_hover_color = hover
                sb._draw()
            except Exception:
                pass

    # -- синхронизация с канвасом -------------------------------------------
    def _auto_set(self, lo, hi):
        """yscrollcommand: запоминаем доли и перекрашиваем полосу."""
        self._thumb_start = float(lo)
        self._thumb_end = float(hi)
        self._schedule_redraw()

    def _schedule_redraw(self):
        """Обновить полосу после завершения текущих событий Tk."""
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
        """Обновить scrollregion и состояние полосы после изменения содержимого."""
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
        self._recolor_scrollbar()
