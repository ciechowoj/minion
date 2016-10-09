import sublime, sublime_plugin
import subprocess, threading
import traceback
import re, time, copy
import os
import queue
import collections


from User.output import *

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
            ignored = config["ignore_errors"]

            if not isinstance(ignored, list):
                ignored = [ignored]

            for item in ignored:
                if item.strip() == line.strip() or re.match(item, line.strip()) != None:
                    return

            panel.append('{}'.format(line))
        else:
            panel.append('{}'.format(line))

    @staticmethod
    def on_cancelled(panel, elapsed_time, config):
        panel.append('[Canceled build.]\n')

    @staticmethod
    def on_finished(panel, return_code, elapsed_time, config, context):
        panel.append_finish_message(
            config['cmd'],
            config['working_dir'],
            return_code,
            elapsed_time)

        window = sublime.active_window()
        window.run_command("minion_next_result", { "action" : "init", "build_system" : config })

        MinionNextErrorCommand.set_list(
            panel.substr(sublime.Region(0, panel.size())),
            config["working_dir"]);


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

ErrorListItem = collections.namedtuple('ErrorListItem', ['file', 'line', 'column', 'source', 'message'])

class MinionNextErrorCommand(sublime_plugin.WindowCommand):
    error_list = []
    prev_error = -1
    working_dir = ""

    def __init__(self, window):
        super().__init__(window)

    def _highlight(self, region):
        panel = OutputView.request()

        if not isinstance(region, sublime.Region):
            region = sublime.Region(region[0], region[1])

        panel.add_regions(
            "error", [region], "error",
            flags = (sublime.DRAW_SQUIGGLY_UNDERLINE
                | sublime.DRAW_NO_FILL | sublime.DRAW_NO_OUTLINE))

        panel.show_at_center(region)

    def run(self, **kwargs):
        error_list = MinionNextErrorCommand.error_list
        prev_error = MinionNextErrorCommand.prev_error

        if len(error_list) == 0:
            sublime.status_message("No errors...")
            return

        direction = -1 if "forward" in kwargs and not kwargs["forward"] else +1
        current_error = (prev_error
            + direction + len(error_list)) % len(error_list)
        MinionNextErrorCommand.prev_error = current_error

        error = error_list[current_error]

        working_dir = os.path.realpath(MinionNextErrorCommand.working_dir)
        basename = "{}:{}:{}".format(error.file, error.line, error.column)
        path = os.path.realpath(os.path.join(working_dir, basename))

        if path.startswith(working_dir):
            self.window.open_file(path, sublime.ENCODED_POSITION)

        self._highlight(error.source)


    @staticmethod
    def _make_default_error_list(buffer):
        def split_error(line):
            split = line.split(":")

            if 2 < len(split) and split[1].isdigit():
                if 3 < len(split) and split[2].isdigit():
                    return (split[0], split[1], split[2], line[sum(map(len, split[0:3])) + 3:])
                return (split[0], split[1], 0, line[sum(map(len, split[0:2])) + 2:])

            return None

        def tilde_and_dash(line):
            line = line.strip()
            return line.count("~") + line.count("^") == len(line)

        def hint(underscore, tentative):
            begin = len(underscore) - len(underscore.lstrip())
            tentative_begin = len(tentative) - len(tentative.lstrip())

            return (begin < tentative_begin
                and len("".join(tentative.split())) < len(underscore) // 2)

        result = []

        lines = list(buffer.splitlines(True))
        itr, size = 0, len(lines)
        offset = 0

        while itr < size:
            split = split_error(lines[itr])

            if split:
                message = lines[itr]

                if itr + 2 < size and tilde_and_dash(lines[itr + 2]):
                    if itr + 3 < size and hint(lines[itr + 2], lines[itr + 3]):
                        message = "".join(lines[itr:itr + 4])
                        itr += 4
                    else:
                        message = "".join(lines[itr:itr + 3])
                        itr += 3
                else:
                    itr += 1

                result.append(
                    ErrorListItem(
                        split[0], split[1], split[2],
                        (offset, offset + len(message)), message))

                offset += len(message)
            else:
                offset += len(lines[itr])
                itr += 1

        return result


    @classmethod
    def make_error_list(klass, buffer, regex):
        if regex == None:
            return klass._make_default_error_list(buffer)
        else:
            return klass._make_regex_error_list(buffer)

    @classmethod
    def _set_list_list(klass, error_list):
        klass.error_list = error_list
        klass.prev_error = -1

    @classmethod
    def _set_list_str(klass, error_list, regex):
        klass._set_list_list(klass.make_error_list(error_list, regex))

    @classmethod
    def set_list(klass, error_list, working_dir, regex = None):
        if isinstance(error_list, list):
            klass._set_list_list(error_list)
        else:
            klass._set_list_str(error_list, regex)

        klass.working_dir = working_dir

    @staticmethod
    def reset_list():
        klass.error_list = []
        klass.prev_error = -1
        klass.working_dir = ""




