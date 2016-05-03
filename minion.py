import sublime, sublime_plugin
import subprocess
import re, os, os.path
from User.build import *
from User.output import *
import traceback

def make_build_system_name(system, variant):
    if system.endswith('.'):
        return "{} - {}".format(system[:-1], variant)
    else:
        return "{} - {}".format(system[:], variant)

class Window:
    def __init__(self, window):
        self.window = window

    def __getattr__(self, name):
        return getattr(self.window, name)

    def get_working_dir(self):
        build_systems = self.project_data()["build_systems"]

        for build_system in build_systems:
            if "working_dir" in build_system:
               return sublime.expand_variables(build_system["working_dir"], self.extract_variables())

        return None

class MinionClearViewCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        self.view.erase(edit, sublime.Region(0, self.view.size()))

class MinionPanelAppendCommand(sublime_plugin.TextCommand):
    def run(self, edit, text):
        scroll = self.view.visible_region().end() == self.view.size()
        self.view.insert(edit, self.view.size(), text)

        if scroll:
            self.view.show(self.view.size())

class MinionNextResultCommand(sublime_plugin.WindowCommand):
    def __init__(self, window):
        super().__init__(window)
        self.position = 0
        self.build_system = None

    def run(self, action = None, **kwargs):
        if action == "init":
            self.position = 0
            self.build_system = kwargs["build_system"]
        else:
            try:
                panel = OutputView.request()
                file_regex = self.build_system["file_regex"]
                region = panel.find(file_regex, self.position)

                self.position = region.end()
                message = panel.substr(region)

                match = re.match(file_regex, message)
                file = match.group(1)
                line = match.group(2)
                column = match.group(3)

                working_dir = self.build_system["working_dir"]
                basename = "{}:{}:{}".format(file, line, column)
                path = os.path.join(working_dir, basename)

                panel.add_regions("error", [region], "error", flags = sublime.DRAW_STIPPLED_UNDERLINE | sublime.DRAW_NO_FILL | sublime.DRAW_NO_OUTLINE)
                panel.show_at_center(region)

                self.window.open_file(path, sublime.ENCODED_POSITION)

                sublime.status_message(message)

            except (AttributeError, TypeError):
                traceback.print_exc()
                sublime.status_message("No more errors...")

class MinionBuildCommand(sublime_plugin.WindowCommand):
    def __init__(self, *args):
        super().__init__(*args)

        self.build_system = None

    def build_systems(self):
        window = self.window
        build_systems_data = self.window.project_data()["build_systems"]
        build_systems_data = expand_variables_ex(build_systems_data, window.extract_variables())

        build_systems = {}

        for data in build_systems_data:
            for key, value in data.items():
                if key == "variants":
                    for variant in value:
                        build_systems[make_build_system_name(data["name"], variant["name"])] = variant
                else:
                    try:
                        build_systems[data["name"]][key] = value
                    except KeyError:
                        build_systems[data["name"]] = { key : value }

        return build_systems

    def run_build(self, config):
        self.window.run_command("save_all")

        config["command"] = config["cmd"]

        self.window.run_command(
            "minion_generic_build",
            { "config" : config })

    def is_project_opened(self):
        return self.window.project_data() != None

    def run_file_build(self):
        view = self.window.active_view()
        if view.file_name().endswith(".cpp"):
            print("Not implemented")
        else:
            print("Not implemented")

    def is_latex_project(self):
        return "latex" in self.window.project_data()

    def build_latex_project(self):
        self.window.run_command("minion_build_latex")

    def run(self):
        if self.is_latex_project():
            self.window.run_command("save_all")
            self.build_latex_project()
        elif self.is_project_opened():
            window = self.window

            OutputView.request().clear()

            build_systems = self.build_systems()

            if self.build_system in build_systems:
                self.run_build(build_systems[self.build_system])
            else:
                build_system_names = sorted(list(build_systems.keys()))

                def on_done(index):
                    self.build_system = build_system_names[index]
                    self.run_build(build_systems[self.build_system])

                window.show_quick_panel(build_system_names, on_done)

        else:
            self.run_file_build()

class MinionCancellBuildCommand(sublime_plugin.WindowCommand):
    def run(self):
        self.window.run_command("minion_generic_build");

class MinionFocusSublimeCommand(sublime_plugin.WindowCommand):
    def window_name(self):
        active = self.window.active_view()
        project = os.path.basename(self.window.project_file_name())
        project = project.replace(".sublime-project", "")

        if active and active.file_name():
            home = os.path.expanduser("~")
            path = active.file_name().replace(home, "~")

            return "{} ({}) - Sublime Text".format(path, project)
        else:
            return "untitled ({}) - Sublime Text".format(project)

    def run(self, depth = 3):
        subprocess.check_call(["wmctrl", "-a", self.window_name()])

        if depth:
            args = ("minion_focus_sublime", { "depth" : depth - 1 })
            sublime.set_timeout_async(lambda: self.window.run_command(*args), 333)

def get_working_dir():
    window = sublime.active_window()

    if window.project_data():
        build_systems = window.project_data()["build_systems"]
        for build_system in build_systems:
            if "working_dir" in build_system:
               return sublime.expand_variables(build_system["working_dir"], window.extract_variables())

    view = window.active_view()
    return os.path.dirname(view.file_name())

class MinionMakeCommand(sublime_plugin.WindowCommand):
    def run(self):
        commands = [
            ("Make - Make", ["make", "-j4"]),
            ("Make - Clean", ["make", "clean"]),
            ("Make - Distclean", ["make", "distclean"])]

        def on_done(index):
            if (index != -1):
                config = {
                    "command" : commands[index][1],
                    "working_dir" : get_working_dir() }

                self.window.run_command("minion_generic_build", { "config" : config })

        self.window.show_quick_panel([x[0] for x in commands], on_done)

class MinionFixLineEndings(sublime_plugin.TextCommand):
    def run(self, edit):
        position = 0
        result = self.view.find("(\\ +)\\n", position)

        while result != None and not result.empty():
            self.view.replace(edit, result, "\n")
            position = result.end()
            result = self.view.find("(\\ +)\\n", position)


class MinionEventListener(sublime_plugin.EventListener):
    def on_pre_save(self, view):
        view.run_command("minion_fix_line_endings")
        # view.run_command("expand_tabs", { "set_translate_tabs": True })
