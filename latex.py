import sublime_plugin

from User.build import *

class MinionBuildLatexCommand(sublime_plugin.WindowCommand):
    ignore = [
        "This is ",
        " restricted .write18 enabled",
        "entering extended mode",
        "LaTeX2e <.*>",
        ".*/usr/share/.*(\\.sty|\\.tex|\\.dfu|\\.def|\\.fd|\\.cfg|\\.cls|\\.clo)",
        ".*/usr/share/texlive.*",
        "Babel <.*> and hyphenation patterns for 3 languages",
        "Document Class: ",
        ".*Beta version. Formatting may change",
        ".*in future versions of this class.",
        "Document language package ",
        ".*Switching to Polish text encoding and Polish maths fonts.",
        r"\*geometry\* driver: auto-detecting",
        r"\*geometry\* detected driver: pdftex",
        "ABD: EveryShipout initializing macros",
        r"\[Loading MPS to PDF converter.*\]",
        r"\(/usr/share/texmf/tex/generic/pgf/frontendlayer/tikz/libraries/t",
        r"hs.code.tex\)\)\) \(.*\)",
        r"Package hyperref (?:Message:|Warning:)",
        r"^\)$",
        r"\[[0-9]*\]",
        r"^\(Font\)",
        r"^\(hyperref\)",
        r"^LaTeX Font Warning:",
        r"^For additional information on amsmath, use the `\?' option.",
        r"^   Inputenc package detected. Catcodes not changed.",
    ]

    def latex_data(self):
        project_data = self.window.project_data()

        if "latex" not in project_data:
            panel = Panel.request_exec_panel(self.window)
            panel.append('[Error: "latex" not present in project settings]')

        latex_data = project_data["latex"]

        if "main" not in latex_data:
            panel = Panel.request_exec_panel(self.window)
            panel.append('[Error: main file not specified (e.g. "main": "main.tex")]')

        return expand_variables_ex(latex_data)

    def filter_single_line(self, panel, line, config, context):
        ignore = False

        for item in MinionBuildLatexCommand.ignore:
            if re.match(item, line) != None:
                ignore = True
                break

        if line.startswith("(./{}".format(config["main"])):
            ignore = True
        elif line == "\n":
            ignore = True

        if ignore:
            context["ignored"] += 1
        else:
            panel.append('{}'.format(line))

    def filter(self, panel, line, config, context):
        verbose = "verbose" in config and config["verbose"]

        if not verbose:
            if "lines" not in context:
                context["lines"] = []

            if "ignored" not in context:
                context["ignored"] = 0

            lines = context["lines"]
            lines.append(line)

            if len(lines) == 5:
                if lines[-5].startswith("*" * 49) and lines[-1].startswith("*" * 49) and lines[-4].startswith("* LaTeX warning:"):
                    lines.clear()
                    context["ignored"] += 1
                else:
                    self.filter_single_line(panel, lines[-5], config, context)
                    lines.pop(0)
        else:
            panel.append('{}'.format(line))

    def on_finished(self, panel, return_code, elapsed_time, config, context):
        if "lines" in context:
            for line in context["lines"]:
                self.filter_single_line(panel, line, config, context)

        if "ignored" in context:
            panel.append("[Ignored {} warnings]\n".format(context["ignored"]))

        panel.append("[Finished]\n")

    def run(self, draft = False, **kwargs):

        print(kwargs)

        latex_data = kwargs

        latex_data["cmd"] = ["pdflatex", "-shell-escape", "-output-directory", "build", latex_data["main"]]

        bibtex_data = {}
        bibtex_data["cmd"] = ["bibtex", "build/" + latex_data["main"].replace(".tex", ".aux")]
        bibtex_data["working_dir"] = latex_data["working_dir"]

        print("Here!", flush = True)
        MinionGenericBuildCommand.run_build(bibtex_data)
        MinionGenericBuildCommand.run_build(latex_data, self.filter, self.on_finished)



class MinionLatexListener(sublime_plugin.EventListener):
    def __init__(self, *args):
        super().__init__(*args)

    def on_post_save(self, view):
        if view.file_name().endswith(".tex"):
            window = view.window()
            window.run_command("build")
