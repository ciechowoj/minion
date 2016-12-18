import sublime, sublime_plugin
import subprocess, threading
import traceback
import re, time, copy
import os
import queue
import collections
import html

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
            config["working_dir"],
            config["file_regex"]);


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

                    MinionNextErrorCommand.reset_list()

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
    phantom_sets = {}

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

    @classmethod
    def _show_phantoms(klass):
        stylesheet = '''
            <style>
                div.error {
                    padding: 0.4rem 0 0.4rem 0.7rem;
                    margin: 0.2rem 0;
                    border-radius: 2px;
                }

                div.error span.message {
                    padding-right: 0.7rem;
                }

                div.error a {
                    text-decoration: inherit;
                    padding: 0.35rem 0.7rem 0.45rem 0.8rem;
                    position: relative;
                    bottom: 0.05rem;
                    border-radius: 0 2px 2px 0;
                    font-weight: bold;
                }
                html.dark div.error a {
                    background-color: #00000018;
                }
                html.light div.error a {
                    background-color: #ffffff18;
                }
            </style>
        '''

        error_list = klass.error_list
        errors_by_file = {}

        for error in error_list:
            if error.file in errors_by_file:
                errors_by_file[error.file].append(error)
            else:
                errors_by_file[error.file] = [error]

        for file, errors in errors_by_file.items():
            view = sublime.active_window().find_open_file(file)

            if view:
                buffer_id = view.buffer_id()

                if buffer_id not in klass.phantom_sets:
                    phantom_set = sublime.PhantomSet(view, "minion")
                    klass.phantom_sets[buffer_id] = phantom_set
                else:
                    phantom_set = klass.phantom_sets[buffer_id]

                phantoms = []

                for _, line, column, _, text in errors:
                    escaped = html.escape(text, quote=False).splitlines()[0].strip()

                    pt = view.text_point(line - 1, max(0, column - 1 - len(escaped) // 2))
                    phantoms.append(sublime.Phantom(
                        sublime.Region(pt, view.line(pt).b),
                        ('<body id=inline-error>' + stylesheet +
                            '<div class="error">' +
                            '<span class="message">' + escaped + '</span>' +
                            '<a href=hide>' + chr(0x00D7) + '</a></div>' +
                            '</body>'),
                        sublime.LAYOUT_BELOW, on_navigate = klass.hide_phantoms))

                phantom_set.update(phantoms)

    @classmethod
    def hide_phantoms(klass, url = None):
        for view in sublime.active_window().views():
            view.erase_phantoms("minion")

        klass.phantom_sets = {}

    @classmethod
    def _make_default_error_list(klass, buffer):
        def split_error(line):
            if line.startswith("In file included from "):
                return None

            if line.startswith("                 from "):
                return None

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

                working_dir = os.path.realpath(klass.working_dir)
                path = os.path.realpath(os.path.join(working_dir, split[0]))

                result.append(
                    ErrorListItem(
                        path,
                        int(split[1]),
                        int(split[2]),
                        (offset, offset + len(message)), message))

                offset += len(message)
            else:
                offset += len(lines[itr])
                itr += 1

        return result

    @classmethod
    def _make_regex_error_list(klass, buffer, regex):
        result = []
        compiled = re.compile(regex)
        offset = 0

        for line in buffer.splitlines(True):
            match = compiled.match(line)

            if match:
                match = match.groups()
                result.append(ErrorListItem(
                    match[0] if len(match) > 0 else "",
                    int(match[1]) if len(match) > 1 and match[1] else 0,
                    int(match[2]) if len(match) > 2 and match[2] else 0,
                    (offset, offset + len(line)),
                    match[3] if len(match) > 3 else line.strip()))

            offset += len(line)

        return result

    @classmethod
    def make_error_list(klass, buffer, regex):
        if regex == None:
            return klass._make_default_error_list(buffer)
        else:
            return klass._make_regex_error_list(buffer, regex)

    @classmethod
    def _set_list_list(klass, error_list):
        klass.error_list = error_list
        klass.prev_error = -1

    @classmethod
    def _set_list_str(klass, error_list, regex):
        klass._set_list_list(klass.make_error_list(error_list, regex))

    @classmethod
    def set_list(klass, error_list, working_dir, regex = None, show_phantoms = True):
        klass.working_dir = working_dir

        if isinstance(error_list, list):
            klass._set_list_list(error_list)
        else:
            klass._set_list_str(error_list, regex)

        if show_phantoms:
            klass._show_phantoms()

    @classmethod
    def reset_list(klass):
        klass.error_list = []
        klass.prev_error = -1
        klass.working_dir = ""
        klass.hide_phantoms()



