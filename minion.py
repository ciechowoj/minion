import sublime, sublime_plugin
import subprocess, threading
import re, os, os.path, time
import queue

def make_build_system_name(system, variant):
    if system.endswith('.'):
        return "{} - {}".format(system[:-1], variant)
    else:
        return "{} - {}".format(system[:], variant)

def expand_variables_ex(value, variables):
    if isinstance(value, str) and value.startswith('${') and value.endswith('}'):
        return sublime.expand_variables(value, variables)
    elif isinstance(value, list):
        return [expand_variables_ex(v, variables) for v in value]
    elif isinstance(value, dict):
        return { k : expand_variables_ex(v, variables) for k, v in value.items() }
    else:
        return value

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

class Panel:
    def __init__(self, view):
        self.view = view

    def __getattr__(self, name):
        return getattr(self.view, name)

    def clear(self):
        self.run_command("minion_clear_view")

    def append(self, text):
        self.run_command("minion_panel_append", { "text" : text })

    def append_finish_message(self, command, working_dir, return_code, elapsed_time):
        if return_code != 0:
            templ = "[Finished in {:.2f}s with exit code {}]\n"
            self.append(templ.format(elapsed_time, return_code))
            self.append("[cmd: {}]\n".format(command))
            self.append("[dir: {}]\n".format(working_dir))
        else:
            self.append("[Finished in {:.2f}s]\n".format(elapsed_time))

    @staticmethod
    def find_panel(window, name):
        panel = window.find_output_panel(name)

        if panel == None:
            return None
        else:
            panel = Panel(panel)
            window.run_command("show_panel", { "panel" : "output.{}".format(name) })
            return panel

    @staticmethod
    def request_panel(window, name):
        panel = Panel.find_panel(window, name)

        if panel == None:
            panel = window.create_output_panel(name)
            return Panel(panel)
        else:
            return panel

    @staticmethod
    def find_exec_panel(window):
        return Panel.find_panel(window, "exec")

    @staticmethod
    def request_exec_panel(window):
        panel = Panel.find_panel(window, "exec")

        if panel == None:
            panel = window.create_output_panel("exec")
            panel.settings().set('color_scheme', "Packages/User/IDLEIDLE.tmTheme")
            panel = Panel(panel)

        window.run_command("show_panel", { "panel" : "output.exec" })
        return panel

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
                panel = Panel.find_exec_panel(self.window)
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

                panel.add_regions("error", [region], "error")
                panel.show_at_center(region)

                view = self.window.open_file(path, sublime.ENCODED_POSITION)

                sublime.status_message(message)

            except (AttributeError, TypeError):
                sublime.status_message("No more errors...")

class MinionBuildCommand(sublime_plugin.WindowCommand):
    def __init__(self, *args):
        super().__init__(*args)

        self.build_system = None
        self.build_process = None
        self.build_result_position = None

    def __del__(self):
        if self.build_process:
            self.build_process.terminate()

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

    def run_build(self, build_system):
        self.window.run_command("save_all")

        if self.build_process != None:
            self.build_process.terminate()
            self.build_process = None
            Panel.find_exec_panel(self.window).clear()

        def callback():
            print(build_system["cmd"])

            self.window.run_command(
                "minion_task_runner",
                {   "method" : "run_task",
                    "command" : build_system["cmd"],
                    "working_dir" : build_system["working_dir"] })

            self.build_result_position = 0

            self.window.run_command("minion_next_result", { "action" : "init", "build_system" : build_system })

        sublime.set_timeout_async(callback, 0)

    def run(self):
        window = self.window

        Panel.request_exec_panel(window).clear()

        build_systems = self.build_systems()

        if self.build_system in build_systems:
            self.run_build(build_systems[self.build_system])
        else:
            build_system_names = sorted(list(build_systems.keys()))

            def on_done(index):
                self.build_system = build_system_names[index]
                self.run_build(build_systems[self.build_system])

            window.show_quick_panel(build_system_names, on_done)

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

class MinionTaskRunnerCommand(sublime_plugin.WindowCommand):
    def __init__(self, *args):
        super().__init__(*args)
        self.workers = []
        self.workers_mutex = threading.Lock()

    def run(self, method, **kwargs):
        getattr(self, method)(**kwargs)

    def run_build(self, build_system):
        pass


    def run_task(self, command, working_dir = None):
        if working_dir == None:
            working_dir = os.path.expanduser("~")

        def target():
            start = time.time()

            process = make_process(command, working_dir)

            with self.workers_mutex:
                self.workers.append((thread, process))

            panel = Panel.request_exec_panel(self.window)

            for line in process.stdout:
                panel.append(line.decode("utf-8"))

            process.wait()

            returncode = process.returncode
            elapsed = time.time() - start

            panel.append_finish_message(command, working_dir, returncode, elapsed)

        thread = threading.Thread(
            target = target,
            daemon = True)

        thread.start()

    def cancel_all(self):
        with self.workers_mutex:
            for thread, process in self.workers:
                try:
                    process.terminate()
                except ProcessLookupError:
                    pass

            self.workers = []

        sublime.status_message("Cancelled all tasks...")

class MinionMakeCommand(sublime_plugin.WindowCommand):
    def run(self):
        window = Window(self.window)

        commands = [
            ("Make - Clean", ["make", "clean"]),
            ("Make - Distclean", ["make", "distclean"])]

        def on_done(index):
            params = {
                "method" : "run_task",
                "command" : commands[index][1],
                "working_dir" : window.get_working_dir() }

            self.window.run_command("minion_task_runner", params)

        self.window.show_quick_panel([x[0] for x in commands], on_done)

class MinionFixLineEndings(sublime_plugin.TextCommand):
    def run(self, edit):
        position = 0
        result = self.view.find("(\\ +)\\n", position)

        while result != None and not result.empty():
            self.view.replace(edit, result, "\n")
            position = result.end()
            result = self.view.find("(\\ +)\\n", position)

class Task:
    class Sentinel:
        pass

    def __init__(self, command, working_dir):
        self.process = subprocess.Popen(
            command,
            stdout = subprocess.PIPE,
            stderr = subprocess.STDOUT,
            cwd = working_dir)

        self.queue = queue.Queue()

        def target():
            for item in self.process.stdout:
                self.queue.put(item)

            self.process.pool()
            self.queue.put(Task.Sentinel())

        self.thread = threading.Thread(target = target, daemon = True)
        self.thread.start()

    def __iter__(self):
        class Generator:
            def __init__(self, queue):
                self.queue = queue

            def __iter__(self):
                return self

            def __next__(self):
                try:
                    while True:
                        item = self.queue.get(True, 0.5)
                        if isinstance(item, Task.Sentinel):
                            raise StopIteration
                        else:
                            return item
                except queue.Empty:
                    return None

        return Generator(self.queue)

    def terminate(self):
        self.process.terminate()

    def return_code(self):
        return self.process.returncode

class MinionBuild2Command(sublime_plugin.WindowCommand):
    thread = None
    cancel = None
    cancel_mutex = threading.Lock()

    def __init__(self, *args):
        super().__init__(*args)

    def __del__(self):
        self.cancel_build()

    def run(self, method, config = None):
        if method == "run":
            config = {}
            config['command'] = ['dub', 'test']
            config['working_dir'] = '/home/wojciech/dstep'
            self.run_build(config)
        elif method == "cancel":
            self.cancel_build()
            
    def filter(self, panel, lines, config):
        panel.append('> {}'.format(lines[-1]))

    def on_cancelled(self, panel, elapsed_time, config):
        panel.append('[Cancelled build.]\n')

    def on_finished(self, panel, return_code, elapsed_time, config):
        panel.append_finish_message(
            config['command'], 
            config['working_dir'], 
            return_code, 
            elapsed_time)

    def run_build(self, config):
        klass = MinionBuild2Command
        self.cancel_build()

        start = time.time()
        process = Task(config['command'], config['working_dir'])
        lines = []
        return_code = None

        panel = Panel.request_exec_panel(self.window)
        panel.clear()
        panel.append("[Building...]\n")

        def worker_main():
            cancelled = False

            for line in process:
                with klass.cancel_mutex:
                    if klass.cancel:
                        process.terminate()
                        cancelled = True
                        break

                if line != None:
                    lines.append(line.decode('utf-8'))
                    self.filter(panel, lines, config)

            elapsed_time = time.time() - start

            if cancelled:
                self.on_cancelled(panel, elapsed_time, config)
            else:
                self.on_finished(panel, process.return_code(), elapsed_time, config)

        klass.thread = threading.Thread(target = worker_main)
        klass.thread.start()

    @classmethod
    def cancel_build(klass):
        if klass.thread:
            with klass.cancel_mutex:
                klass.cancel = True
            klass.thread.join(8)
            klass.thread = None
            klass.cancel = False

def plugin_unloaded():
    MinionBuild2Command.cancel_build()





 






