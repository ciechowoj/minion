import sublime, sublime_plugin
import os.path, re
import textwrap

def find_unmatched_braces(s):
    OPEN = "({["
    CLOSE = ")}]"
    stack = []

    itr = 0
    end = len(s)

    line = 1
    column = 1

    while itr < end:
        if s[itr] in OPEN:
            stack.append((s[itr], itr, line, column))
        elif s[itr] in CLOSE:
            if stack[-1][0] == OPEN[CLOSE.index(s[itr])]:
                stack.pop()
            else:
                return stack[-1][1:]

        if s[itr] == '\n':
            line += 1
            column = 1
        else:
            column += 1

        itr += 1

    return None

def find_matching_brace(s, p):
    OPEN = "({["
    CLOSE = ")}]"

    if s[p] in OPEN:
        itr = find_closing_brace(s, p)

        if itr != None and s[itr] == CLOSE[OPEN.index(s[p])]:
            return itr

    elif s[p] in CLOSE:
        itr = find_opening_brace(s, p)

        if itr != None and s[itr] == OPEN[CLOSE.index(s[p])]:
            return itr

    return None

def find_opening_brace(s, p):
    OPEN = "({["
    CLOSE = ")}]"
    stack = []

    itr = p - 1
    end = -1

    while itr > end:
        if s[itr] in CLOSE:
            stack.append(s[itr])
        elif s[itr] in OPEN:
            if stack == []:
                return itr
            elif stack[-1] == CLOSE[OPEN.index(s[itr])]:
                stack.pop()
            else:
                raise Exception("Unmatched braces.")

        itr -= 1

    return None

def find_closing_brace(s, p):
    OPEN = "({["
    CLOSE = ")}]"
    stack = []

    itr = p + 1
    end = len(s)

    while itr < end:
        if s[itr] in OPEN:
            stack.append(s[itr])
        elif s[itr] in CLOSE:
            if stack == []:
                return itr
            elif stack[-1] == OPEN[CLOSE.index(s[itr])]:
                stack.pop()
            else:
                raise Exception("Unmatched braces.")

        itr += 1

    if itr < end:
        return itr
    else:
        return None

def find_experimental_config(content):
    config = content.find('"configurations"')
    config_begin = content.find('[', config)
    config_end = find_matching_brace(content, config_begin) + 1
    config = content[config_begin:config_end]

    exp = re.search('"name":\s*"experimental"', config)

    if exp:
        exp = exp.start()
        exp_begin = find_opening_brace(config, exp)
        exp_end = find_matching_brace(config, exp_begin) + 1

        while exp_begin != 0 and config[exp_begin - 1].isspace():
            exp_begin -= 1

        if exp_begin != 0 and config[exp_begin - 1] == ",":
            exp_begin -= 1

        while (exp_end < len(config) and config[exp_end].isspace() and
                config[exp_end] != "\n"):
            exp_end += 1

        return (config_begin + exp_begin, config_begin + exp_end)

    return None

def find_experimental_end(content):
    config = content.find('"configurations"')
    config_begin = content.find('[', config)
    config_end = find_matching_brace(content, config_begin)

    indent_begin = config_end
    indent_end = config_end

    while indent_begin != 0 and content[indent_begin - 1] != '\n':
        indent_begin -= 1

    while config_end != 0 and content[config_end - 1].isspace():
        config_end -= 1

    return config_end, content[indent_begin:indent_end]

EXPERIMENTAL = """

{
    "name": "experimental",
    "mainSourceFile": "experimental.d",
    "targetName": "experimental",
    "sourcePaths": ["dstep", "clang", "unit_tests"],
    "importPaths": ["dstep", "clang"],
    "lflags-posix": ["-lclang", "-rpath", ".", "-L.", "-L/usr/lib64/llvm", "-L/usr/lib/llvm-3.7/lib"],
    "lflags-windows": ["+\\\\", "+clang"],
    "excludedSourceFiles": ["dstep/main.d"]
}"""

class ToggleExperimentalConfigCommand(sublime_plugin.WindowCommand):
    def enable_experimental_config(self, path):
        content = open(path, "r").read()
        config, indent = find_experimental_end(content)

        if config != None:
            content = content[:config] + "," + textwrap.indent(EXPERIMENTAL, indent * 2) + content[config:]

        open(path, "w+").write(content)

    def disable_experimental_config(self, path):
        content = open(path, "r").read()
        config = find_experimental_config(content)

        while config != None:
            begin, end = config
            content = content[:begin] + content[end:]
            config = find_experimental_config(content)

        open(path, "w+").write(content)

    def run(self, enable = True):
        project_path = self.window.extract_variables()["project_path"]
        dub_json_path = os.path.join(project_path, "dub.json")

        if not os.path.isfile(dub_json_path):
            sublime.error_message("`{}` doesn't exist.".format(dub_json_path))
        else:
            if enable:
                print("enable")
                self.enable_experimental_config(dub_json_path)
            else:
                print("")
                self.disable_experimental_config(dub_json_path)
