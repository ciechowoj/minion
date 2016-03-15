import sublime, sublime_plugin
import subprocess, threading
import traceback
import re, time, copy
import os
import queue

def expand_variables_ex(value, variables = None):
    variables = variables if variables else sublime.active_window().extract_variables()

    if isinstance(value, str) and value.startswith('${') and value.endswith('}'):
        return sublime.expand_variables(value, variables)
    elif isinstance(value, list):
        return [expand_variables_ex(v, variables) for v in value]
    elif isinstance(value, dict):
        return { k : expand_variables_ex(v, variables) for k, v in value.items() }
    else:
        return value

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
    def request_exec_panel(window = None):
        if window == None:
            window = sublime.active_window()

        panel = Panel.find_panel(window, "exec")

        if panel == None:
            panel = window.create_output_panel("exec")
            panel.settings().set('color_scheme', "Packages/User/IDLEIDLE.tmTheme")
            panel = Panel(panel)

        window.run_command("show_panel", { "panel" : "output.exec" })
        return panel

class Task:
    class Sentinel:
        pass

    def __init__(self, command, working_dir):
        env = copy.copy(os.environ)
        env["max_print_line"] = "1048576"

        self.process = subprocess.Popen(
            command,
            stdout = subprocess.PIPE,
            stderr = subprocess.STDOUT,
            cwd = working_dir,
            env = env)

        self.queue = queue.Queue()

        def target():
            for item in self.process.stdout:
                self.queue.put(item)

            self.process.wait()
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

class MinionGenericBuildCommand(sublime_plugin.WindowCommand):
    worker_thread = None
    worker_mutex = threading.Lock()
    build_queue = queue.Queue()

    def __init__(self, *args):
        super().__init__(*args)

    def __del__(self):
        self.cancel_build()

    def run(self, config = None):
        MinionGenericBuildCommand.run_build(
            config,
            self.filter,
            MinionGenericBuildCommand.on_cancelled,
            )

    @staticmethod
    def filter(panel, lines, config):
        if "ignore_errors" in config:
            if re.match(config["ignore_errors"], lines[-1]) == None:
                panel.append('{}'.format(lines[-1]))
        else:
            panel.append('{}'.format(lines[-1]))

    @staticmethod
    def on_cancelled(panel, elapsed_time, config):
        panel.append('[Cancelled build.]\n')

    @staticmethod
    def on_finished(panel, return_code, elapsed_time, config):
        panel.append_finish_message(
            config['command'],
            config['working_dir'],
            return_code,
            elapsed_time)

        window = sublime.active_window()
        window.run_command("minion_next_result", { "action" : "init", "build_system" : config })

    @classmethod
    def run_build(klass, config, filter = None, on_finished = None, on_cancelled = None):
        filter = filter if filter != None else MinionGenericBuildCommand.filter
        on_finished = on_finished if on_finished else MinionGenericBuildCommand.on_finished
        on_cancelled = on_cancelled if on_cancelled else MinionGenericBuildCommand.on_cancelled

        def target():
            while True:
                config, filter, on_finished, on_cancelled = klass.build_queue.get()

                if config != None:
                    start = time.time()

                    try:
                        process = Task(config['command'], config['working_dir'])            

                        lines = []

                        panel = Panel.request_exec_panel()
                        panel.clear()
                        panel.append("[Building...]\n")

                        cancelled = False

                        for line in process:
                            if not klass.build_queue.empty():
                                process.terminate()
                                cancelled = True
                                break

                            if line != None:
                                lines.append(line.decode('utf-8'))
                                filter(panel, lines, config)

                        elapsed_time = time.time() - start

                        if cancelled:
                            on_cancelled(panel, elapsed_time, config)
                        else:
                            on_finished(panel, process.return_code(), elapsed_time, config)
                    except Exception as exception:
                        panel = Panel.request_exec_panel()
                        panel.clear()
                        panel.append("[Running task {} failed.]\n".format(config['command']))
                        traceback.print_exc()

        with klass.worker_mutex:
            if klass.worker_thread == None:
                klass.worker_thread = threading.Thread(
                    target = target,
                    daemon = True)
                klass.worker_thread.start()

        klass.build_queue.put((config, filter, on_finished, on_cancelled))

    @classmethod
    def cancel_build(klass):
        with klass.worker_mutex:
            if klass.worker_thread:
                klass.build_queue.put_nowait((None, None, None, None))

def plugin_unloaded():
    MinionGenericBuildCommand.cancel_build()
