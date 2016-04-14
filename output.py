import sublime, sublime_plugin

def clean_layout(layout):
    row_set = set()
    col_set = set()

    for cell in layout["cells"]:
        row_set.add(cell[1])
        row_set.add(cell[3])
        col_set.add(cell[0])
        col_set.add(cell[2])

    row_set = sorted(row_set)
    col_set = sorted(col_set)

    rows = layout["rows"]
    cols = layout["cols"]

    layout["rows"] = [row for i, row in enumerate(rows) if i in row_set]
    layout["cols"] = [col for i, col in enumerate(cols) if i in col_set]

    row_map = { row : i for i, row in enumerate(row_set) }
    col_map = { col : i for i, col in enumerate(col_set) }

    layout["cells"] = [[col_map[cell[0]], row_map[cell[1]], col_map[cell[2]], row_map[cell[3]]] for cell in layout["cells"]]

    return layout

def collapse_group(group):
    LEFT = 0
    TOP = 1
    RIGHT = 2
    BOTTOM = 3

    window = sublime.active_window()
    layout = window.get_layout()
    cells = layout["cells"]

    new_cells = []
    group_cell = cells[group]
    cells = cells[:group] + cells[group + 1:]

    for cell in cells:
        if cell[BOTTOM] == group_cell[TOP] and cell[LEFT] >= group_cell[LEFT] and cell[RIGHT] <= group_cell[RIGHT]:
            new_cells.append([
                cell[LEFT],
                cell[TOP],
                cell[RIGHT],
                group_cell[BOTTOM]
                ])

        elif cell != group_cell:
            new_cells.append(cell)

    layout["cells"] = new_cells

    window.set_layout(clean_layout(layout))

class OutputView:
    content = ""
    position = 0.0
    id = None

    def __init__(self, view):
        self.view = view

    def __getattr__(self, name):
        if self.view.id() != id:
            output = OutputView.find_view()
            if output:
                self.view = output.view

        return getattr(self.view, name)

    def clear(self):
        OutputView.content = ""
        self.run_command("output_view_clear")

    def append(self, text):
        OutputView.content += text
        self.run_command("output_view_append", { "text" : text })

    def append_finish_message(self, command, working_dir, return_code, elapsed_time):
        if return_code != 0:
            templ = "[Finished in {:.2f}s with exit code {}]\n"
            self.append(templ.format(elapsed_time, return_code))
            self.append("[cmd: {}]\n".format(command))
            self.append("[dir: {}]\n".format(working_dir))
        else:
            self.append("[Finished in {:.2f}s]\n".format(elapsed_time))

    def _collapse(self, group):
        window = sublime.active_window()
        views = window.views_in_group(group)

        if (len(views) == 0 or len(views) == 1 and
            views[0].id() == self.view.id()):
            collapse_group(group)

    def _close(self):
        window = sublime.active_window()
        group, index = window.get_view_index(self.view)
        window.run_command("close_by_index", {"group": group, "index": index})
        self._collapse(group)
        OutputView.id = None

    @staticmethod
    def close():
        window = sublime.active_window()

        for view in window.views():
            if view.is_scratch() and view.name() == "Output":
                OutputView(view)._close()

    @staticmethod
    def find_view():
        window = sublime.active_window()

        for view in window.views():
            if view.is_scratch() and view.name() == "Output":
                return OutputView(view)

        return None

    @staticmethod
    def request():
        window = sublime.active_window()
        num_groups = window.num_groups()

        if num_groups < 3:
            layout = window.get_layout()
            num_rows = len(layout["rows"]) - 1
            num_cols = len(layout["cols"]) - 1

            if len(layout["rows"]) < 3:
                begin = layout["rows"][-2]
                end = layout["rows"][-1]
                layout["rows"] = layout["rows"][:-1] + [begin * 0.33 + end * 0.66, layout["rows"][-1]]

                cells = []
                new_num_rows = len(layout["rows"]) - 1
                for cell in layout["cells"]:
                    if cell[3] == num_rows and cell[2] != num_cols:
                        cells.append([cell[0], cell[1], cell[2], new_num_rows])
                    else:
                        cells.append(cell)

                cells.append([num_cols - 1, new_num_rows - 1, num_cols, new_num_rows])
                layout["cells"] = cells

                window.set_layout(layout)

        num_groups = window.num_groups()
        views = window.views_in_group(num_groups - 1)
        output = None

        for view in views:
            if view.name() == "Output" and view.is_scratch():
                output = view

        if output == None:
            active = window.active_view()
            output = window.new_file()
            output.settings().set("line_numbers", False)
            output.settings().set("scroll_past_end", False)
            output.settings().set("scroll_speed", 0.0)
            output.settings().set("gutter", False)
            output.set_scratch(True)
            output.set_name("Output")
            output.run_command("output_view_append", { "text" : OutputView.content })

            def update():
                output.set_viewport_position((0, OutputView.position), False)

            sublime.set_timeout(update, 0.0)

            OutputView.id = output.id()
            window.set_view_index(output, num_groups - 1, len(views))
            window.focus_view(active)

        return OutputView(output)


class OutputViewClearCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        self.view.erase(edit, sublime.Region(0, self.view.size()))

class OutputViewAppendCommand(sublime_plugin.TextCommand):
    def run(self, edit, text):
        scroll = self.view.visible_region().end() == self.view.size()
        view = self.view
        view.insert(edit, view.size(), text)

        if scroll:
            viewport = view.viewport_extent()
            last_line = view.text_to_layout(view.size())
            view.set_viewport_position((0, last_line[1] - viewport[1]), False)

class OpenOutputCommand(sublime_plugin.WindowCommand):
    def run(self):
        OutputView.request()

class CloseOutputCommand(sublime_plugin.WindowCommand):
    def run(self):
        OutputView.close()

class OutputEventListener(sublime_plugin.EventListener):
    def on_query_context(self, view, key, operator, operand, match_all):
        if key == "output_visible":
            return OutputView.find_view() != None
        else:
            return None

    def on_close(self, view):
        if view.is_scratch() and view.name() == "Output":
            OutputView.position = view.viewport_position()[1]
