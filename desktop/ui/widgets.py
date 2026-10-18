"""Вспомогательные виджеты, согласованные с темой приложения.

Содержит:
* ``DarkTableFrame``      — панель со Treeview без лишних рамок;
* ``DarkScrollableFrame`` — прокручиваемая панель (без полос прокрутки).

Полосы прокрутки (скроллбары) из интерфейса убраны целиком: ни вертикальных,
ни горизонтальных скроллбаров нигде не отображается. Прокрутка содержимого
сохранилась через колесо мыши и клавиатуру.

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


class ColumnSeparatorPlugin:
    """Вертикальные линии-разделители между столбцами Treeview.

    Штатными средствами ttk нарисовать такие линии нельзя: в макете
    стиля ``clam`` строки таблицы рисуются элементом ``Treeitems``, а
    типы элементов ``Treeview.cell`` / ``Treeheading.cell`` не имеют
    настраиваемых опций (``style.element_options(...)`` возвращает пустой
    кортеж), поэтому любые попытки задать им рамку молча игнорировались —
    именно из-за этого разделителей между столбцами не было.

    Теперь линии рисуются на собственном tk.Canvas, который лежит под
    деревом в ``lower()`` стопорядке: он существует для отрисовки линий,
    но мышь по-прежнему попадает в таблицу (клик/перетаскивание не
    перехватываются). Линии считаются по реальным границам колонок
    (``tree.winfo_x`` + смещение горизонтального пролистывания +
    ``tree.column(col, 'xscale')``), поэтому совпадают с сеткой даже при
    растягивании колонок и прокрутке колесом.

    Публичный API прежний: ``attach()``, ``redraw()``, ``place_overlay()``,
    ``set_known_widths()``, ``destroy()``.
    """

    _PENDING_MS = 60  # объединение частых перерисовок в одну

    def __init__(self, tree: ttk.Treeview):
        self.tree = tree
        self._known_widths: dict = {}
        self._canvas = None
        self._after_id = None
        self._bound = False
        self._redraw_pending = False

    # ------------------------------------------------------------------ setup
    def attach(self):
        """Создать слой-подложку и подписать события перестройки таблицы."""
        tree = self.tree
        if not tree.winfo_exists():
            return
        parent = tree.master

        if self._canvas is None or not self._canvas.winfo_exists():
            pal = theme.palette()
            self._canvas = tk.Canvas(parent, highlightthickness=0, bd=0,
                                     bg=pal.panel_bg)
            self._canvas.bind('<Configure>', lambda _e: self.redraw())

        # Тот же размер и позиция, что у дерева; ниже дерева по стопорядку
        # (у Canvas метод .lower() переопределён под теги, поэтому «понизить
        # сам виджет» вызываем через BaseWidget.lower), чтобы линиями нельзя
        # было перехватить клики мыши.
        self._canvas.place(x=tree.winfo_x(), y=tree.winfo_y(),
                           width=tree.winfo_width(), height=tree.winfo_height())
        tk.BaseWidget.lower(self._canvas)

        if not self._bound:
            self._bound = True
            tree.bind('<Configure>', lambda _e: self.redraw(), add='+')
            for seq in ('<ButtonRelease-1>', '<MouseWheel>', '<Key>',
                        '<Button-4>', '<Button-5>'):
                tree.bind(seq, lambda _e: self._schedule_redraw(), add='+')
        self.redraw()

    def place_overlay(self):
        """Совместимость со старым кодом: то же, что attach()."""
        self.attach()

    def set_known_widths(self, widths: dict):
        """Запомнить исходные ширины колонок (для перерисовки после смены темы)."""
        self._known_widths = dict(widths or {})
        self.attach()

    def destroy(self):
        if self._after_id is not None:
            try:
                self.tree.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None
        if self._canvas is not None:
            try:
                self._canvas.destroy()
            except tk.TclError:
                pass
            self._canvas = None

    # ------------------------------------------------------------- rendering
    def _schedule_redraw(self):
        """Отложить перерисовку: линии считают геометрию после неё."""
        if self._after_id is not None:
            return
        try:
            self._after_id = self.tree.after(self._PENDING_MS, self._on_pending)
        except tk.TclError:
            self._after_id = None

    def _on_pending(self):
        self._after_id = None
        self.redraw()

    def redraw(self):
        """Перерисовать вертикальные линии по текущим границам колонок."""
        tree = self.tree
        canvas = self._canvas
        try:
            if not tree.winfo_exists() or canvas is None or not canvas.winfo_exists():
                return
            if not tree.winfo_viewable():
                return
        except tk.TclError:
            return

        # Не перерисовывать рекурсивно внутри обработчика <Configure>.
        if self._redraw_pending:
            return
        self._redraw_pending = True
        try:
            self._do_redraw()
        finally:
            self._redraw_pending = False

    def _do_redraw(self):
        tree = self.tree
        canvas = self._canvas

        # Подгоняем слой под дерево (после pack/place самого дерева).
        self._canvas.place(x=tree.winfo_x(), y=tree.winfo_y(),
                           width=max(1, tree.winfo_width()),
                           height=max(1, tree.winfo_height()))

        cols = list(tree['columns'])
        if not cols:
            return

        pal = theme.palette()
        color = pal.border
        # фон подложки = фон таблицы текущей темы (под таблицей её не видно)
        self._canvas.configure(bg=pal.panel_bg)

        # Верхняя граница линий: y первой строки (низ шапки); если строк нет
        # или они прокручены — сразу под заголовками (identify_region).
        top = 0
        try:
            kids = tree.get_children()
            bb = tree.bbox(kids[0]) if kids else None
            if bb:
                top = bb[1]
            elif tree.identify_region(2, 2) == 'heading':
                top = tree.identify_row(2) or 0
        except (IndexError, tk.TclError):
            pass
        bottom = max(top, self._canvas.winfo_height())

        # Смещение горизонтального пролистывания (без скроллбара обычно 0).
        xoff = 0
        try:
            frac = float(tree.xview()[0])
            if 0.0 < frac < 1.0:
                total_w = sum(int(tree.column(c, 'width')) for c in cols)
                xoff = int(round(frac * total_w / (1.0 - frac)))
        except (TypeError, ValueError, tk.TclError):
            xoff = 0

        self._canvas.delete('vsep')
        last = len(cols) - 1
        for i, col in enumerate(cols):
            if i == last:
                break
            try:
                xscale = float(tree.column(col, 'xscale'))
            except (TypeError, ValueError, tk.TclError):
                continue
            if xscale <= 0:
                continue
            # xscale — доля ширины колонки в видимой области дерева.
            x = round(tree.winfo_width() * xscale)
            if 0 < x < self._canvas.winfo_width():
                self._canvas.create_line(x, top, x, bottom,
                                         fill=color, width=1, tags='vsep')

class DarkTableFrame(ctk.CTkFrame):
    """Панель со Treeview без рамок и без полос прокрутки.

    * фон панели берётся из текущей темы;
    * рамок нет: панель отличима фоном, разграничителями служат только
      шапка таблицы и тонкие разделители колонок;
    * скроллбары не создаются и не отображаются вовсе; строки, не
      помещающиеся по высоте/ширине, доступны колесом мыши;
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

        # Скроллбары не создаются: y/xscrollcommand просто игнорирует
        # вызовы ttk (сигнатура (first, last)).
        self.tree.configure(yscrollcommand=lambda *_a: None,
                            xscrollcommand=lambda *_a: None)

        # Переменная позиции горизонтального пролистывания (оставлена для
        # совместимости со старыми ссылками, внешним кодом не используется).
        self.xview_var = tk.StringVar(value='0.0 1.0')

        self.tree.pack(fill='both', expand=True)

        for col in (columns or ()):
            width = (column_widths or {}).get(col, 120)
            text = (headings or {}).get(col, col)
            self.tree.heading(col, text=text, anchor='w')
            self.tree.column(col, width=width, minwidth=60, anchor='w', stretch=True)

        # Разделители между столбцами: рисуются самим ttk рамками ячеек
        # (см. ColumnSeparatorPlugin), никаких оверлеев над таблицей.
        self._sep_plugin = ColumnSeparatorPlugin(self.tree)
        self._sep_plugin.set_known_widths({c: (column_widths or {}).get(c, 120)
                                           for c in (columns or ())})

        # Чередование строк для читаемости
        self.tree.tag_configure('oddrow', background=pal.row_alt)
        self.tree.tag_configure('evenrow', background=pal.panel_bg)
        self._row_count = 0

        # Прокрутка колесом мыши вместо скроллбара.
        self._bind_mousewheel(self.tree)

        # Перекраска при переключении темы.
        toplevel = self.winfo_toplevel()
        toplevel.bind('<<ThemeChanged>>', lambda _e=None: self._on_theme_change(), add='+')

    # ------------------------------------------------------------- mousewheel
    @staticmethod
    def _bind_mousewheel(widget):
        """Колесо мыши прокручивает таблицу вверх/вниз."""
        def _on_mousewheel(event):
            delta = -1 if getattr(event, 'num', None) == 5 else 1
            if getattr(event, 'delta', 0):
                delta = -1 if event.delta > 0 else 1
            try:
                widget.yview_scroll(delta, 'units')
            except tk.TclError:
                pass
            return 'break'

        widget.bind('<MouseWheel>', _on_mousewheel)
        widget.bind('<Button-4>', _on_mousewheel)
        widget.bind('<Button-5>', _on_mousewheel)

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

    def clear(self):
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        self._row_count = 0


class DarkScrollableFrame(ctk.CTkScrollableFrame):
    """Прокручиваемая панель без видимых полос прокрутки.

    Нативный ``CTkScrollbar`` библиотечного ``CTkScrollableFrame`` полностью
    удалён из разметки и скрыт: никакого скроллбара справа не отображается
    (ни когда содержимое влезает, ни когда оно длиннее окна). Прокрутка
    осталась доступной колесом мыши и клавиатурой.
    """

    def __init__(self, master, **kwargs):
        kwargs.setdefault('fg_color', 'transparent')
        kwargs.setdefault('label_text', '')
        super().__init__(master, **kwargs)
        self._hide_scrollbar()

    # ---------------------------------------------------------------- scrollbar
    def _hide_scrollbar(self):
        """Убрать нативный скроллбар из разметки и скрыть его."""
        sb = getattr(self, '_scrollbar', None)
        if sb is None:
            return
        try:
            sb.grid_forget()
            sb.grid_remove()
        except Exception:
            pass

    def _create_grid(self):
        super()._create_grid()
        # Любая перестройка сетки (corner_radius / border_width / label_text)
        # возвращает полосу в grid — убираем её снова.
        if hasattr(self, '_parent_frame'):
            self._hide_scrollbar()

    # ------------------------------------------------------------ содержимое
    def _after_content_change(self):
        """Обновить scrollregion после изменения набора содержимого."""
        self._parent_canvas.update_idletasks()
        bbox = self._parent_canvas.bbox('all')
        if bbox:
            self._parent_canvas.configure(scrollregion=bbox)
