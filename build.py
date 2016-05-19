import sublime, sublime_plugin
import subprocess, threading
import traceback
import re, time, copy
import os
import queue
from User.output import *

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
            self.filter)

    @staticmethod
    def filter(panel, line, config, context):
        if "ignore_errors" in config:
            if re.match(config["ignore_errors"], line) == None:
                panel.append('{}'.format(line))
        else:
            panel.append('{}'.format(line))

    @staticmethod
    def on_cancelled(panel, elapsed_time, config):
        panel.append('[Cancelled build.]\n')

    @staticmethod
    def on_finished(panel, return_code, elapsed_time, config, context):
        panel.append_finish_message(
            config['cmd'],
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
                        process = Task(config['cmd'], config['working_dir'])

                        context = {}

                        output = OutputView.request()
                        output.clear()
                        output.append("[Building...]\n")

                        cancelled = False

                        for line in process:
                            if not klass.build_queue.empty():
                                process.terminate()
                                cancelled = True
                                break

                            if line != None:
                                filter(output, line.decode('utf-8'), config, context)

                        elapsed_time = time.time() - start

                        if cancelled:
                            on_cancelled(output, elapsed_time, config)
                        else:
                            on_finished(output, process.return_code(), elapsed_time, config, context)
                    except Exception:
                        output = OutputView.request()
                        output.clear()
                        output.append("[Running task {} failed.]\n".format(config['cmd']))
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
